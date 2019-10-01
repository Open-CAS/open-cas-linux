/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils/utils_blk.h"
#include "threads.h"

extern u32 max_writeback_queue_size;
extern u32 writeback_queue_unblock_size;
extern u32 metadata_layout;
extern u32 unaligned_io;
extern u32 seq_cut_off_mb;
extern u32 use_io_scheduler;

struct _cache_mngt_sync_context {
	struct completion compl;
	int *result;
};

static void _cache_mngt_lock_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_lock_sync(ocf_cache_t cache)
{
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_lock(cache, _cache_mngt_lock_complete, &context);
	wait_for_completion_interruptible(&context.compl);

	return result;
}

static int _cache_mngt_read_lock_sync(ocf_cache_t cache)
{
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_read_lock(cache, _cache_mngt_lock_complete, &context);
	wait_for_completion_interruptible(&context.compl);

	return result;
}

static void _cache_mngt_save_sync_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_save_sync(ocf_cache_t cache)
{
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_save(cache, _cache_mngt_save_sync_complete, &context);
	wait_for_completion_interruptible(&context.compl);

	return result;
}

static void _cache_mngt_cache_flush_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_cache_flush_sync(ocf_cache_t cache, bool interruption)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	atomic_set(&cache_priv->flush_interrupt_enabled, 0);
	ocf_mngt_cache_flush(cache, _cache_mngt_cache_flush_complete, &context);
	wait_for_completion_interruptible(&context.compl);
	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

static void _cache_mngt_core_flush_complete(ocf_core_t core, void *priv,
		int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_core_flush_sync(ocf_core_t core, bool interruption)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	atomic_set(&cache_priv->flush_interrupt_enabled, 0);
	ocf_mngt_core_flush(core, _cache_mngt_core_flush_complete, &context);
	wait_for_completion_interruptible(&context.compl);
	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

static void _cache_mngt_cache_stop_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_cache_stop_sync(ocf_cache_t cache)
{
	struct _cache_mngt_sync_context context;
	int result;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_stop(cache, _cache_mngt_cache_stop_complete, &context);
	wait_for_completion_interruptible(&context.compl);

	return result;
}

static uint16_t find_free_cache_id(ocf_ctx_t ctx)
{
	ocf_cache_t cache;
	uint16_t id;
	int result;

	for (id = OCF_CACHE_ID_MIN; id < OCF_CACHE_ID_MAX; id++) {
		result = mngt_get_cache_by_id(ctx, id, &cache);
		if (!result)
			ocf_mngt_cache_put(cache);
		else if (result == -OCF_ERR_CACHE_NOT_EXIST)
			break;
		else
			return OCF_CACHE_ID_INVALID;
	}

	return id;
}

static uint64_t _ffz(uint64_t word)
{
	int i;

	for (i = 0; i < sizeof(word)*8 && (word & 1); i++)
		word >>= 1;

	return i;
}

static uint16_t find_free_core_id(uint64_t *bitmap)
{
	uint16_t i, ret = OCF_CORE_MAX;
	bool zero_core_free = !(*bitmap & 0x1UL);

	/* check if any core id is free except 0 */
	for (i = 0; i * sizeof(uint64_t) * 8 < OCF_CORE_MAX; i++) {
		uint64_t ignore_mask = (i == 0) ? 1UL : 0UL;
		if (~(bitmap[i] | ignore_mask)) {
			ret = min((uint64_t)OCF_CORE_MAX,
					(uint64_t)(i * sizeof(uint64_t) * 8
					+ _ffz(bitmap[i] | ignore_mask)));
			break;
		}
	}

	/* return 0 only if no other core is free */
	if (ret == OCF_CORE_MAX && zero_core_free)
		return 0;

	return ret;
}

static void mark_core_id_used(uint64_t *bitmap, uint16_t core_id)
{
	set_bit(core_id, (unsigned long *)bitmap);
}

static void mark_core_id_free(uint64_t *bitmap, uint16_t core_id)
{
	clear_bit(core_id, (unsigned long *)bitmap);
}

int cache_mngt_flush_object(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					cache_name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = ocf_core_get_by_name(cache, core_name, core_name_len, &core);
	if (result)
		goto out;

	result = _cache_mngt_core_flush_sync(core, true);

out:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_flush_device(const char *cache_name, size_t name_len)
{
	int result;
	ocf_cache_t cache;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_cache_flush_sync(cache, true);

	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_set_cleaning_policy(ocf_cache_t cache, uint32_t type)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_set_policy(cache, type);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_cleaning_policy(ocf_cache_t cache, uint32_t *type)
{
	ocf_cleaning_t tmp_type;
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_get_policy(cache, &tmp_type);

	if (result == 0)
		*type = tmp_type;

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
		uint32_t param_id, uint32_t param_value)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_set_param(cache, type,
			param_id, param_value);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
		uint32_t param_id, uint32_t *param_value)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_get_param(cache, type,
			param_id, param_value);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_promotion_policy(ocf_cache_t cache, uint32_t type)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_set_policy(cache, type);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_promotion_policy(ocf_cache_t cache, uint32_t *type)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		return result;
	}

	*type = ocf_mngt_cache_promotion_get_policy(cache);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_promotion_param(ocf_cache_t cache, uint32_t param_id,
		uint32_t param_value)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_set_param(cache, param_id, param_value);

	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_promotion_param(ocf_cache_t cache, uint32_t param_id,
		uint32_t *param_value)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_get_param(cache, param_id, param_value);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

struct get_paths_ctx {
	char *core_path_name_tab;
	int max_count;
	int position;
};

int _cache_mngt_core_pool_get_paths_visitor(ocf_uuid_t uuid, void *ctx)
{
	struct get_paths_ctx *visitor_ctx = ctx;

	if (visitor_ctx->position >= visitor_ctx->max_count)
		return 0;

	if (copy_to_user((void __user *)visitor_ctx->core_path_name_tab +
			(visitor_ctx->position * MAX_STR_LEN),
			uuid->data, uuid->size)) {
		return -ENODATA;
	}

	visitor_ctx->position++;

	return 0;
}

int cache_mngt_core_pool_get_paths(struct kcas_core_pool_path *cmd_info)
{
	struct get_paths_ctx visitor_ctx = {0};
	int result;

	visitor_ctx.core_path_name_tab = cmd_info->core_path_tab;
	visitor_ctx.max_count = cmd_info->core_pool_count;

	result = ocf_mngt_core_pool_visit(cas_ctx,
			_cache_mngt_core_pool_get_paths_visitor,
			&visitor_ctx);

	cmd_info->core_pool_count = visitor_ctx.position;
	return result;
}

int cache_mngt_core_pool_remove(struct kcas_core_pool_remove *cmd_info)
{
	struct ocf_volume_uuid uuid;
	ocf_volume_t vol;

	uuid.data = cmd_info->core_path_name;
	uuid.size = strnlen(cmd_info->core_path_name, MAX_STR_LEN);

	vol = ocf_mngt_core_pool_lookup(cas_ctx, &uuid,
			ocf_ctx_get_volume_type(cas_ctx,
					BLOCK_DEVICE_VOLUME));
	if (!vol)
		return -OCF_ERR_CORE_NOT_AVAIL;

	ocf_volume_close(vol);
	ocf_mngt_core_pool_remove(cas_ctx, vol);

	return 0;
}

struct cache_mngt_metadata_probe_context {
	struct completion compl;
	struct kcas_cache_check_device *cmd_info;
	int *result;
};

static void cache_mngt_metadata_probe_end(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct cache_mngt_metadata_probe_context *context = priv;
	struct kcas_cache_check_device *cmd_info = context->cmd_info;

	*context->result = error;

	if (error == -OCF_ERR_NO_METADATA || error == -OCF_ERR_METADATA_VER) {
		cmd_info->is_cache_device = false;
		*context->result = 0;
	} else if (error == 0) {
		cmd_info->is_cache_device = true;
		cmd_info->clean_shutdown = status->clean_shutdown;
		cmd_info->cache_dirty = status->cache_dirty;
	}

	complete(&context->compl);
}

int cache_mngt_cache_check_device(struct kcas_cache_check_device *cmd_info)
{
	struct cache_mngt_metadata_probe_context context;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK CACHE DEVICE\n";
	int result;

	bdev = blkdev_get_by_path(cmd_info->path_name, (FMODE_EXCL|FMODE_READ),
			holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	result = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (result)
		goto out_bdev;

	cmd_info->format_atomic = (ocf_ctx_get_volume_type_id(cas_ctx,
			ocf_volume_get_type(volume)) == ATOMIC_DEVICE_VOLUME);

	init_completion(&context.compl);
	context.cmd_info = cmd_info;
	context.result = &result;

	ocf_metadata_probe(cas_ctx, volume, cache_mngt_metadata_probe_end,
			&context);
	wait_for_completion_interruptible(&context.compl);

	cas_blk_close_volume(volume);
out_bdev:
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));
	return result;
}

int cache_mngt_prepare_core_cfg(struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info)
{
	struct block_device *bdev;
	char core_name[OCF_CORE_NAME_SIZE] = {};
	ocf_cache_t cache;
	uint16_t core_id;
	int result;

	if (strnlen(cmd_info->core_path_name, MAX_STR_LEN) >= MAX_STR_LEN)
		return -OCF_ERR_INVAL;

	if (cmd_info->core_id == OCF_CORE_MAX) {
		result = mngt_get_cache_by_id(cas_ctx, cmd_info->cache_id,
				&cache);
		if (result && result != -OCF_ERR_CACHE_NOT_EXIST) {
			return result;
		} else if (!result) {
			struct cache_priv *cache_priv;
			cache_priv = ocf_cache_get_priv(cache);
			ocf_mngt_cache_put(cache);

			core_id = find_free_core_id(cache_priv->core_id_bitmap);
			if (core_id == OCF_CORE_MAX)
				return -OCF_ERR_INVAL;

			cmd_info->core_id = core_id;
		}
	}

	snprintf(core_name, sizeof(core_name), "core%d", cmd_info->core_id);

	memset(cfg, 0, sizeof(*cfg));
	env_strncpy(cfg->name, OCF_CORE_NAME_SIZE, core_name, OCF_CORE_NAME_SIZE);

	cfg->uuid.data = cmd_info->core_path_name;
	cfg->uuid.size = strnlen(cmd_info->core_path_name, MAX_STR_LEN) + 1;
	cfg->try_add = cmd_info->try_add;

	if (cas_upgrade_is_in_upgrade()) {
		cfg->volume_type = BLOCK_DEVICE_VOLUME;
		return 0;
	}

	bdev = CAS_LOOKUP_BDEV(cfg->uuid.data);
	if (IS_ERR(bdev))
		return -OCF_ERR_INVAL_VOLUME_TYPE;
	bdput(bdev);

	if (cmd_info->update_path)
		return 0;

	result = cas_blk_identify_type(cfg->uuid.data, &cfg->volume_type);
	if (!result && cfg->volume_type == ATOMIC_DEVICE_VOLUME)
		result = -KCAS_ERR_NVME_BAD_FORMAT;
	if (OCF_ERR_NOT_OPEN_EXC == abs(result)) {
		printk(KERN_WARNING OCF_PREFIX_SHORT
			"Cannot open device %s exclusively. "
		        "It is already opened by another program!\n",
			cmd_info->core_path_name);
	}

	return result;
}

static int cache_mngt_update_core_uuid(ocf_cache_t cache, const char *core_name,
				size_t name_len, ocf_uuid_t uuid)
{
	ocf_core_t core;
	ocf_volume_t vol;
	struct block_device *bdev;
	struct bd_object *bdvol;
	bool match;
	int result;

	if (ocf_core_get_by_name(cache, core_name, name_len, &core)) {
		/* no such core */
		return -ENODEV;
	}

	if (ocf_core_get_state(core) != ocf_core_state_active) {
		/* core inactive */
		return -ENODEV;
	}

	/* get bottom device volume for this core */
	vol = ocf_core_get_volume(core);
	bdvol = bd_object(vol);

	/* lookup block device object for device pointed by uuid */
	bdev =  CAS_LOOKUP_BDEV(uuid->data);
	if (IS_ERR(bdev)) {
		printk(KERN_ERR "failed to lookup bdev%s\n", (char*)uuid->data);
		return -ENODEV;
	}

	/* check whether both core id and uuid point to the same block device */
	match = (bdvol->btm_bd == bdev);

	bdput(bdev);

	if (!match) {
		printk(KERN_ERR "UUID provided does not match target core device\n");
		return -ENODEV;
	}

	result = ocf_mngt_core_set_uuid(core, uuid);
	if (result)
		return result;

	return _cache_mngt_save_sync(cache);
}

static void _cache_mngt_log_core_device_path(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	const ocf_uuid_t core_uuid = (const ocf_uuid_t)ocf_core_get_uuid(core);

	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as core %s "
			"to cache %s\n", (const char*)core_uuid->data,
			ocf_core_get_name(core), ocf_cache_get_name(cache));
}

static int _cache_mngt_core_device_loaded_visitor(ocf_core_t core, void *cntx)
{
	struct cache_priv *cache_priv;
	uint16_t core_id = OCF_CORE_ID_INVALID;
	ocf_cache_t cache = ocf_core_get_cache(core);
	cache_priv = ocf_cache_get_priv(cache);

	_cache_mngt_log_core_device_path(core);

	core_id_from_name(&core_id, ocf_core_get_name(core));

	mark_core_id_used(cache_priv->core_id_bitmap, core_id);

	return 0;
}

struct _cache_mngt_add_core_context {
	struct completion compl;
	ocf_core_t *core;
	int *result;
};

/************************************************************
 * Function for adding a CORE object to the cache instance. *
 ************************************************************/

static void _cache_mngt_add_core_complete(ocf_cache_t cache,
		ocf_core_t core, void *priv, int error)
{
	struct _cache_mngt_add_core_context *context = priv;

	*context->core = core;
	*context->result = error;
	complete(&context->compl);
}

static void _cache_mngt_remove_core_complete(void *priv, int error);

int cache_mngt_add_core_to_cache(const char *cache_name, size_t name_len,
		struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info)
{
	struct _cache_mngt_add_core_context add_context;
	struct _cache_mngt_sync_context remove_context;
	ocf_cache_t cache;
	ocf_core_t core;
	int result, remove_core_result;
	struct cache_priv *cache_priv;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (cfg->try_add && (result == -OCF_ERR_CACHE_NOT_EXIST)) {
		result = ocf_mngt_core_pool_add(cas_ctx, &cfg->uuid,
				cfg->volume_type);
		if (result) {
			cmd_info->ext_err_code =
					-OCF_ERR_CANNOT_ADD_CORE_TO_POOL;
			printk(KERN_ERR OCF_PREFIX_SHORT
					"Error occurred during"
					" adding core to detached core pool\n");
		} else {
			printk(KERN_INFO OCF_PREFIX_SHORT
					"Successfully added"
					" core to core pool\n");
		}
		return result;
	} else if (result) {
		return result;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	if (cmd_info && cmd_info->update_path) {
		result = cache_mngt_update_core_uuid(cache, cfg->name,
						OCF_CORE_NAME_SIZE, &cfg->uuid);
		ocf_mngt_cache_unlock(cache);
		ocf_mngt_cache_put(cache);
		return result;
	}

	cfg->seq_cutoff_threshold = seq_cut_off_mb * MiB;

	init_completion(&add_context.compl);
	add_context.core = &core;
	add_context.result = &result;

	ocf_mngt_cache_add_core(cache, cfg, _cache_mngt_add_core_complete,
			&add_context);
	wait_for_completion_interruptible(&add_context.compl);
	if (result)
		goto error_affter_lock;

	result = block_dev_create_exported_object(core);
	if (result)
		goto error_after_add_core;

	result = block_dev_activate_exported_object(core);
	if (result)
		goto error_after_create_exported_object;


	cache_priv = ocf_cache_get_priv(cache);
	mark_core_id_used(cache_priv->core_id_bitmap, cmd_info->core_id);

	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);

	_cache_mngt_log_core_device_path(core);

	return 0;

error_after_create_exported_object:
	block_dev_destroy_exported_object(core);

error_after_add_core:
	init_completion(&remove_context.compl);
	remove_context.result = &remove_core_result;
	ocf_mngt_cache_remove_core(core, _cache_mngt_remove_core_complete,
			&remove_context);
	wait_for_completion_interruptible(&remove_context.compl);

error_affter_lock:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);

	return result;
}

/* Flush cache and destroy exported object */
int _cache_mngt_remove_core_prepare(ocf_cache_t cache, ocf_core_t core,
		struct kcas_remove_core *cmd, bool destroy)
{
	int result = 0;
	int flush_result = 0;
	bool core_active;
	bool flush_interruptible = !destroy;

	core_active = (ocf_core_get_state(core) == ocf_core_state_active);

	if (cmd->detach && !core_active) {
		printk(KERN_WARNING OCF_PREFIX_SHORT
				"Cannot detach core which "
				"is already inactive!\n");
		return -OCF_ERR_CORE_IN_INACTIVE_STATE;
	}

	if (core_active && destroy) {
		result = block_dev_destroy_exported_object(core);
		if (result)
			return result;
	}

	if (!cmd->force_no_flush) {
		if (core_active) {
			/* Flush core */
			flush_result = _cache_mngt_core_flush_sync(core,
					flush_interruptible);
		} else {
			printk(KERN_WARNING OCF_PREFIX_SHORT
					"Cannot remove inactive core "
					"without force option\n");
			return -OCF_ERR_CORE_IN_INACTIVE_STATE;
		}
	}

	if (flush_result)
		result = destroy ? -KCAS_ERR_REMOVED_DIRTY : flush_result;

	return result;
}

/****************************************************************
 * Function for removing a CORE object from the cache instance
 ****************************************************************/

static void _cache_mngt_remove_core_complete(void *priv, int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

int cache_mngt_remove_core_from_cache(struct kcas_remove_core *cmd)
{
	struct _cache_mngt_sync_context context;
	int result, flush_result = 0;
	ocf_cache_t cache;
	ocf_core_t core;
	struct cache_priv *cache_priv;

	result = mngt_get_cache_by_id(cas_ctx, cmd->cache_id, &cache);
	if (result)
		return result;

	if (!cmd->force_no_flush) {
		/* First check state and flush data (if requested by user)
		   under read lock */
		result = _cache_mngt_read_lock_sync(cache);
		if (result)
			goto put;

		result = get_core_by_id(cache, cmd->core_id, &core);
		if (result < 0)
			goto rd_unlock;

		result = _cache_mngt_remove_core_prepare(cache, core, cmd,
				false);
		if (result)
			goto rd_unlock;

		ocf_mngt_cache_read_unlock(cache);
	}

	/* Acquire write lock */
	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto put;

	result = get_core_by_id(cache, cmd->core_id, &core);
	if (result < 0) {
		goto unlock;
	}

	/*
	 * Destroy exported object and flush core again but don't allow for
	 * interruption - in case of flush error after exported object had been
	 * destroyed, instead of trying rolling this back we rather detach core
	 * and then inform user about error.
	 */
	result = _cache_mngt_remove_core_prepare(cache, core, cmd, true);
	if (result == -KCAS_ERR_REMOVED_DIRTY) {
		flush_result = result;
		result = 0;
	} else if (result) {
		goto unlock;
	}

	init_completion(&context.compl);
	context.result = &result;

	if (cmd->detach || flush_result) {
		ocf_mngt_cache_detach_core(core,
				_cache_mngt_remove_core_complete, &context);
	} else {
		ocf_mngt_cache_remove_core(core,
				_cache_mngt_remove_core_complete, &context);
	}

	if (!cmd->force_no_flush && !flush_result)
		BUG_ON(ocf_mngt_core_is_dirty(core));

	wait_for_completion_interruptible(&context.compl);

	if (!result && cmd->detach) {
		cache_priv = ocf_cache_get_priv(cache);
		mark_core_id_free(cache_priv->core_id_bitmap, cmd->core_id);
	}

	if (!result && flush_result)
		result = flush_result;

unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;

rd_unlock:
	ocf_mngt_cache_read_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_reset_stats(const char *cache_name, size_t cache_name_len,
				const char *core_name, size_t core_name_len)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result = 0;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, cache_name_len,
						&cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	if (core_name) {
		result = ocf_core_get_by_name(cache, core_name,
					core_name_len, &core);
		if (result)
			goto out;

		ocf_core_stats_initialize(core);
	} else {
		ocf_core_stats_initialize_all(cache);
	}

out:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

static inline void io_class_info2cfg(ocf_part_id_t part_id,
		struct ocf_io_class_info *info, struct ocf_mngt_io_class_config *cfg)
{
	cfg->class_id = part_id;
	cfg->name = info->name;
	cfg->prio = info->priority;
	cfg->cache_mode = info->cache_mode;
	cfg->min_size = info->min_size;
	cfg->max_size = info->max_size;
}

int cache_mngt_set_partitions(const char *cache_name, size_t name_len,
		struct kcas_io_classes *cfg)
{
	ocf_cache_t cache;
	struct ocf_mngt_io_classes_config *io_class_cfg;
	struct cas_cls_rule *cls_rule[OCF_IO_CLASS_MAX];
	ocf_part_id_t class_id;
	int result;

	io_class_cfg = kzalloc(sizeof(struct ocf_mngt_io_class_config) *
			OCF_IO_CLASS_MAX, GFP_KERNEL);
	if (!io_class_cfg)
		return -OCF_ERR_NO_MEM;

	for (class_id = 0; class_id < OCF_IO_CLASS_MAX; class_id++) {
		io_class_cfg->config[class_id].class_id = class_id;

		if (!cfg->info[class_id].name[0]) {
			io_class_cfg->config[class_id].class_id = class_id;
			continue;
		}

		io_class_info2cfg(class_id, &cfg->info[class_id],
				&io_class_cfg->config[class_id]);
	}

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		goto out_get;

	for (class_id = 0; class_id < OCF_IO_CLASS_MAX; class_id++) {
		result = cas_cls_rule_create(cache, class_id,
				cfg->info[class_id].name,
				&cls_rule[class_id]);
		if (result)
			goto out_cls;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto out_cls;

	result = ocf_mngt_cache_io_classes_configure(cache, io_class_cfg);
	if (result == -OCF_ERR_IO_CLASS_NOT_EXIST)
		result = 0;
	if(result)
		goto out_configure;

	result = _cache_mngt_save_sync(cache);
	if (result)
		goto out_configure;

	for (class_id = 0; class_id < OCF_IO_CLASS_MAX; class_id++)
		cas_cls_rule_apply(cache, class_id, cls_rule[class_id]);

out_configure:
	ocf_mngt_cache_unlock(cache);
out_cls:
	if (result) {
		while (class_id--)
			cas_cls_rule_destroy(cache, cls_rule[class_id]);
	}
	ocf_mngt_cache_put(cache);
out_get:
	kfree(io_class_cfg);
	return result;
}

static int _cache_mngt_create_exported_object(ocf_core_t core, void *cntx)
{
	int result;
	ocf_cache_t cache = ocf_core_get_cache(core);

	result = block_dev_create_exported_object(core);
	if (result) {
		printk(KERN_ERR "Cannot to create exported object, %s.%s\n",
				ocf_cache_get_name(cache),
				ocf_core_get_name(core));
		return result;
	}

	result = block_dev_activate_exported_object(core);
	if (result) {
		printk(KERN_ERR "Cannot to activate exported object, %s.%s\n",
				ocf_cache_get_name(cache),
				ocf_core_get_name(core));
	}

	return result;
}

static int _cache_mngt_destroy_exported_object(ocf_core_t core, void *cntx)
{
	if (block_dev_destroy_exported_object(core)) {
		ocf_cache_t cache = ocf_core_get_cache(core);

		printk(KERN_ERR "Cannot to destroy exported object, %s.%s\n",
				ocf_cache_get_name(cache),
				ocf_core_get_name(core));
	}

	return 0;
}

static int cache_mngt_initialize_core_objects(ocf_cache_t cache)
{
	int result;

	result = ocf_core_visit(cache, _cache_mngt_create_exported_object, NULL,
			true);
	if (result) {
		/* Need to cleanup */
		ocf_core_visit(cache, _cache_mngt_destroy_exported_object, NULL,
				true);
	}

	return result;
}

int cache_mngt_prepare_cache_cfg(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct atomic_dev_params *atomic_params,
		struct kcas_start_cache *cmd)
{
	int init_cache, result;
	struct block_device *bdev;
	int part_count;
	char holder[] = "CAS START\n";
	char cache_name[OCF_CACHE_NAME_SIZE];
	uint16_t cache_id;
	bool is_part;

	if (strnlen(cmd->cache_path_name, MAX_STR_LEN) >= MAX_STR_LEN)
		return -OCF_ERR_INVAL;

	if (cmd->cache_id == OCF_CACHE_ID_INVALID) {
		cache_id = find_free_cache_id(cas_ctx);
		if (cache_id == OCF_CACHE_ID_INVALID)
			return -OCF_ERR_INVAL;

		cmd->cache_id = cache_id;
	}

	cache_name_from_id(cache_name, cmd->cache_id);

	memset(cfg, 0, sizeof(*cfg));
	memset(device_cfg, 0, sizeof(*device_cfg));
	memset(atomic_params, 0, sizeof(*atomic_params));

	strncpy(cfg->name, cache_name, OCF_CACHE_NAME_SIZE - 1);
	cfg->cache_mode = cmd->caching_mode;
	cfg->cache_line_size = cmd->line_size;
	cfg->eviction_policy = cmd->eviction_policy;
	cfg->promotion_policy = ocf_promotion_default;
	cfg->cache_line_size = cmd->line_size;
	cfg->pt_unaligned_io = !unaligned_io;
	cfg->use_submit_io_fast = !use_io_scheduler;
	cfg->locked = true;
	cfg->metadata_volatile = false;
	cfg->metadata_layout = metadata_layout;

	cfg->backfill.max_queue_size = max_writeback_queue_size;
	cfg->backfill.queue_unblock_size = writeback_queue_unblock_size;

	device_cfg->uuid.data = cmd->cache_path_name;
	device_cfg->uuid.size = strnlen(device_cfg->uuid.data, MAX_STR_LEN) + 1;
	device_cfg->cache_line_size = cmd->line_size;
	device_cfg->force = cmd->force;
	device_cfg->perform_test = true;
	device_cfg->discard_on_start = true;

	init_cache = cmd->init_cache;

	switch (init_cache) {
	case CACHE_INIT_LOAD:
		device_cfg->open_cores = true;
	case CACHE_INIT_NEW:
		break;
	default:
		return -OCF_ERR_INVAL;
	}

	bdev = blkdev_get_by_path(device_cfg->uuid.data, (FMODE_EXCL|FMODE_READ),
			holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	is_part = (bdev->bd_contains != bdev);
	part_count = cas_blk_get_part_count(bdev);
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));

	if (!is_part && part_count > 1 && !device_cfg->force)
		return -KCAS_ERR_CONTAINS_PART;

	result = cas_blk_identify_type_atomic(device_cfg->uuid.data,
			&device_cfg->volume_type, atomic_params);
	if (result)
		return result;

	if (device_cfg->volume_type == ATOMIC_DEVICE_VOLUME)
		device_cfg->volume_params = atomic_params;

	cmd->metadata_mode_optimal =
			block_dev_is_metadata_mode_optimal(atomic_params,
					device_cfg->volume_type);

	return 0;
}

static void _cache_mngt_log_cache_device_path(ocf_cache_t cache,
		struct ocf_mngt_cache_device_config *device_cfg)
{
	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as cache %s\n",
			(const char*)device_cfg->uuid.data,
			ocf_cache_get_name(cache));
}

static void _cas_queue_kick(ocf_queue_t q)
{
	return cas_kick_queue_thread(q);
}

static void _cas_queue_stop(ocf_queue_t q)
{
	return cas_stop_queue_thread(q);
}


const struct ocf_queue_ops queue_ops = {
	.kick = _cas_queue_kick,
	.stop = _cas_queue_stop,
};

static int _cache_mngt_start_queues(ocf_cache_t cache)
{
	uint32_t cpus_no = num_online_cpus();
	struct cache_priv *cache_priv;
	int result, i;

	cache_priv = ocf_cache_get_priv(cache);

	for (i = 0; i < cpus_no; i++) {
		result = ocf_queue_create(cache, &cache_priv->io_queues[i],
				&queue_ops);
		if (result)
			goto err;

		result = cas_create_queue_thread(cache_priv->io_queues[i], i);
		if (result) {
			ocf_queue_put(cache_priv->io_queues[i]);
			goto err;
		}
	}

	result = ocf_queue_create(cache, &cache_priv->mngt_queue, &queue_ops);
	if (result)
		goto err;

	result = cas_create_queue_thread(cache_priv->mngt_queue, CAS_CPUS_ALL);
	if (result) {
		ocf_queue_put(cache_priv->mngt_queue);
		goto err;
	}

	ocf_mngt_cache_set_mngt_queue(cache, cache_priv->mngt_queue);

	return 0;
err:
	while (--i >= 0)
		ocf_queue_put(cache_priv->io_queues[i]);

	return result;
}

struct _cache_mngt_attach_context {
	struct completion compl;
	int *result;
};

static void _cache_mngt_attach_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_attach_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

static int _cache_mngt_cache_priv_init(ocf_cache_t cache)
{
	struct cache_priv *cache_priv;
	uint32_t cpus_no = num_online_cpus();

	cache_priv = vzalloc(sizeof(*cache_priv) +
			cpus_no * sizeof(*cache_priv->io_queues));
	if (!cache_priv)
		return -OCF_ERR_NO_MEM;

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	ocf_cache_set_priv(cache, cache_priv);

	return 0;
}

static void _cache_mngt_cache_priv_deinit(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	vfree(cache_priv);
}

static int _cache_mngt_start(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct kcas_start_cache *cmd, ocf_cache_t *cache)
{
	struct _cache_mngt_attach_context context;
	ocf_cache_t tmp_cache;
	ocf_queue_t mngt_queue = NULL;
	struct cache_priv *cache_priv;
	int result;

	result = ocf_mngt_cache_start(cas_ctx, &tmp_cache, cfg);
	if (result)
		return result;

	result = _cache_mngt_cache_priv_init(tmp_cache);
	BUG_ON(result);

	/* Currently we can't recover without queues setup. OCF doesn't
	 * support stopping cache when management queue isn't started. */

	result = _cache_mngt_start_queues(tmp_cache);
	BUG_ON(result);

	/* Ditto */

	cache_priv = ocf_cache_get_priv(tmp_cache);
	mngt_queue = cache_priv->mngt_queue;

	result = cas_cls_init(tmp_cache);
	if (result)
		goto err_classifier;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_attach(tmp_cache, device_cfg,
			_cache_mngt_attach_complete, &context);

	wait_for_completion_interruptible(&context.compl);
	if (result)
		goto err_attach;

	_cache_mngt_log_cache_device_path(tmp_cache, device_cfg);

	*cache = tmp_cache;

	return 0;

err_attach:
	if (result == -OCF_ERR_NO_FREE_RAM && cmd) {
		ocf_mngt_get_ram_needed(tmp_cache, device_cfg,
				&cmd->min_free_ram);
	}
	cas_cls_deinit(tmp_cache);
err_classifier:
	_cache_mngt_cache_priv_deinit(tmp_cache);
	_cache_mngt_cache_stop_sync(tmp_cache);
	if (mngt_queue)
		ocf_queue_put(mngt_queue);
	ocf_mngt_cache_unlock(tmp_cache);
	return result;
}

struct _cache_mngt_load_context {
	struct completion compl;
	int *result;
};

static void _cache_mngt_load_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_load_context *context = priv;

	*context->result = error;
	complete(&context->compl);
}

struct cache_mngt_check_metadata_context {
	struct completion compl;
	char *cache_name;
	int *result;
};

static void cache_mngt_check_metadata_end(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct cache_mngt_check_metadata_context *context = priv;

	*context->result = error;

	if (error == -OCF_ERR_NO_METADATA || error == -OCF_ERR_METADATA_VER) {
		printk(KERN_ERR "Failed to load cache metadata!\n");
	} else if (strncmp(status->cache_name, context->cache_name,
			OCF_CACHE_NAME_SIZE)) {
		*context->result = -OCF_ERR_CACHE_NAME_MISMATCH;
		printk(KERN_ERR "Loaded cache name is invalid: %s!\n",
				status->cache_name);
	}

	complete(&context->compl);
}

static int _cache_mngt_check_metadata(struct ocf_mngt_cache_config *cfg,
		char *cache_path_name)
{
	struct cache_mngt_check_metadata_context context;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK METADATA\n";
	int result;

	bdev = blkdev_get_by_path(cache_path_name, (FMODE_EXCL|FMODE_READ),
			holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
			-OCF_ERR_NOT_OPEN_EXC :
			-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	result = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (result)
		goto out_bdev;

	init_completion(&context.compl);
	context.cache_name = cfg->name;
	context.result = &result;

	ocf_metadata_probe(cas_ctx, volume, cache_mngt_check_metadata_end,
			&context);
	wait_for_completion_interruptible(&context.compl);

	cas_blk_close_volume(volume);
out_bdev:
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));
	return result;
}

static int _cache_mngt_load(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct kcas_start_cache *cmd, ocf_cache_t *cache)
{
	struct _cache_mngt_load_context context;
	ocf_cache_t tmp_cache;
	ocf_queue_t mngt_queue = NULL;
	struct cache_priv *cache_priv;
	int result;

	result = _cache_mngt_check_metadata(cfg, cmd->cache_path_name);
	if (result)
		return result;

	result = ocf_mngt_cache_start(cas_ctx, &tmp_cache, cfg);
	if (result)
		return result;

	result = _cache_mngt_cache_priv_init(tmp_cache);
	BUG_ON(result);

	/* Currently we can't recover without queues setup. OCF doesn't
	 * support stopping cache when management queue isn't started. */

	result = _cache_mngt_start_queues(tmp_cache);
	BUG_ON(result);

	/* Ditto */

	cache_priv = ocf_cache_get_priv(tmp_cache);
	mngt_queue = cache_priv->mngt_queue;

	init_completion(&context.compl);
	context.result = &result;

	ocf_mngt_cache_load(tmp_cache, device_cfg,
			_cache_mngt_load_complete, &context);

	wait_for_completion_interruptible(&context.compl);
	if (result)
		goto err_load;

	_cache_mngt_log_cache_device_path(tmp_cache, device_cfg);

	result = cas_cls_init(tmp_cache);
	if (result)
		goto err_load;

	result = cache_mngt_initialize_core_objects(tmp_cache);
	if (result)
		goto err_core_obj;

	ocf_core_visit(tmp_cache, _cache_mngt_core_device_loaded_visitor,
			NULL, false);

	*cache = tmp_cache;

	return 0;

err_core_obj:
	cas_cls_deinit(tmp_cache);
err_load:
	if (result == -OCF_ERR_NO_FREE_RAM && cmd) {
		ocf_mngt_get_ram_needed(tmp_cache, device_cfg,
				&cmd->min_free_ram);
	}
	_cache_mngt_cache_priv_deinit(tmp_cache);
	_cache_mngt_cache_stop_sync(tmp_cache);
	if (mngt_queue)
		ocf_queue_put(mngt_queue);
	ocf_mngt_cache_unlock(tmp_cache);
	return result;
}

int cache_mngt_init_instance(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct kcas_start_cache *cmd)
{
	ocf_cache_t cache = NULL;
	const char *name;
	bool load = (cmd && cmd->init_cache == CACHE_INIT_LOAD);
	int result;

	if (!try_module_get(THIS_MODULE))
		return -KCAS_ERR_SYSTEM;

	/* Start cache. Returned cache instance will be locked as it was set
	 * in configuration.
	 */
	if (!load)
		result = _cache_mngt_start(cfg, device_cfg, cmd, &cache);
	else
		result = _cache_mngt_load(cfg, device_cfg, cmd, &cache);

	if (result) {
		module_put(THIS_MODULE);
		return result;
	}

	if (cmd) {
		ocf_volume_t cache_obj;
		struct bd_object *bd_cache_obj;
		struct block_device *bdev;

		cache_obj = ocf_cache_get_volume(cache);
		BUG_ON(!cache_obj);

		bd_cache_obj = bd_object(cache_obj);
		bdev = bd_cache_obj->btm_bd;

		/* If we deal with whole device, reread partitions */
		if (bdev->bd_contains == bdev)
			ioctl_by_bdev(bdev, BLKRRPART, (unsigned long)NULL);

		/* Set other back information */
		name = block_dev_get_elevator_name(
				casdsk_disk_get_queue(bd_cache_obj->dsk));
		if (name)
			strlcpy(cmd->cache_elevator,
					name, MAX_ELEVATOR_NAME);
	}

	ocf_mngt_cache_unlock(cache);

	return 0;
}

/**
 * @brief routine implementing dynamic sequential cutoff parameter switching
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] thresh new sequential cutoff threshold value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_set_seq_cutoff_threshold(ocf_cache_t cache, ocf_core_t core,
		uint32_t thresh)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core) {
		result = ocf_mngt_core_set_seq_cutoff_threshold(core, thresh);
	} else {
		result = ocf_mngt_core_set_seq_cutoff_threshold_all(cache,
				thresh);
	}

	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief routine implementing dynamic sequential cutoff parameter switching
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] policy new sequential cutoff policy value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_set_seq_cutoff_policy(ocf_cache_t cache, ocf_core_t core,
		ocf_seq_cutoff_policy policy)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core)
		result = ocf_mngt_core_set_seq_cutoff_policy(core, policy);
	else
		result = ocf_mngt_core_set_seq_cutoff_policy_all(cache, policy);

	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief Get sequential cutoff threshold value
 * @param[in] core OCF core
 * @param[out] thresh sequential cutoff threshold value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_get_seq_cutoff_threshold(ocf_core_t core, uint32_t *thresh)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_core_get_seq_cutoff_threshold(core, thresh);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

/**
 * @brief Get sequential cutoff policy
 * @param[in] core OCF core
 * @param[out] thresh sequential cutoff policy
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_get_seq_cutoff_policy(ocf_core_t core,
		ocf_seq_cutoff_policy *policy)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_core_get_seq_cutoff_policy(core, policy);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

/**
 * @brief routine implementing dynamic cache mode switching
 * @param cache_name name of cache to which operation applies
 * @param mode target mode (WRITE_THROUGH, WRITE_BACK, WRITE_AROUND etc.)
 * @param flush shall we flush dirty data during switch, or shall we flush
 *            all remaining dirty data before entering new mode?
 */
int cache_mngt_set_cache_mode(const char *cache_name, size_t name_len,
			ocf_cache_mode_t mode, uint8_t flush)
{
	ocf_cache_mode_t old_mode;
	ocf_cache_t cache;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	old_mode = ocf_cache_get_mode(cache);

	result = ocf_mngt_cache_set_mode(cache, mode);
	if (result)
		goto out;

	if (flush) {
		result = _cache_mngt_cache_flush_sync(cache, true);
		if (result) {
			ocf_mngt_cache_set_mode(cache, old_mode);
			goto out;
		}
	}

	result = _cache_mngt_save_sync(cache);
	if (result)
		ocf_mngt_cache_set_mode(cache, old_mode);

out:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

/**
 * @brief routine implements --stop-cache command.
 * @param[in] cache_name caching device name to be removed
 * @param[in] flush Boolean: shall we flush dirty data before removing cache.
 *		if yes, flushing may still be interrupted by user (in which case
 *		device won't be actually removed and error will be returned)
 */
int cache_mngt_exit_instance(const char *cache_name, size_t name_len, int flush)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	int status, flush_status = 0;

	/* Get cache */
	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (status)
		return status;

	cache_priv = ocf_cache_get_priv(cache);

	status = _cache_mngt_read_lock_sync(cache);
	if (status)
		goto put;
	/*
	 * Flush cache. Flushing may take a long time, so we allow user
	 * to interrupt this operation. Hence we do first flush before
	 * disabling exported object to avoid restoring it in case
	 * of interruption. That means some new dirty data could appear
	 * in cache during flush operation which will not be flushed
	 * this time, so we need to flush cache again after disabling
	 * exported object. The second flush should be much faster.
	 */
	if (flush) {
		status = _cache_mngt_cache_flush_sync(cache, true);
		switch (status) {
		case -OCF_ERR_CACHE_IN_INCOMPLETE_STATE:
		case -OCF_ERR_FLUSHING_INTERRUPTED:
			ocf_mngt_cache_read_unlock(cache);
			goto put;
		default:
			flush_status = status;
			break;
		}
	}

	ocf_mngt_cache_read_unlock(cache);

	/* get cache write lock */
	status = _cache_mngt_lock_sync(cache);
	if (status)
		goto put;

	if (!cas_upgrade_is_in_upgrade()) {
		/* If we are not in upgrade - destroy cache devices */
		status = block_dev_destroy_all_exported_objects(cache);
		if (status != 0) {
			printk(KERN_WARNING
				"Failed to remove all cached devices\n");
			goto unlock;
		}
	} else {
		if (flush_status) {
			status = flush_status;
			goto unlock;
		}
		/*
		 * We are being switched to upgrade in flight mode -
		 * wait for finishing pending core requests
		 */
		cache_mngt_wait_for_rq_finish(cache);
	}

	/* Flush cache again. This time we don't allow interruption. */
	if (flush)
		flush_status = _cache_mngt_cache_flush_sync(cache, false);

	if (flush && !flush_status)
		BUG_ON(ocf_mngt_cache_is_dirty(cache));

	/* Stop cache device */
	status = _cache_mngt_cache_stop_sync(cache);
	if (status && status != -OCF_ERR_WRITE_CACHE)
		goto restore_exp_obj;

	if (!status && flush_status)
		status = -KCAS_ERR_STOPPED_DIRTY;

	module_put(THIS_MODULE);

	cas_cls_deinit(cache);

	ocf_queue_put(cache_priv->mngt_queue);
	vfree(cache_priv);

	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);

	return status;

restore_exp_obj:
	if (block_dev_create_all_exported_objects(cache)) {
		/* Print error msg but do not change return err code to inform user why
		* stop failed originally. */
		printk(KERN_WARNING
			"Failed to restore (create) all exported objects!\n");
		goto unlock;
	}
	if (block_dev_activate_all_exported_objects(cache)) {
		block_dev_destroy_all_exported_objects(cache);
		printk(KERN_WARNING
			"Failed to restore (activate) all exported objects!\n");
	}
unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return status;
}

static int cache_mngt_list_caches_visitor(ocf_cache_t cache, void *cntx)
{
	struct kcas_cache_list *list = cntx;
	uint16_t id;

	BUG_ON(cache_id_from_name(&id, ocf_cache_get_name(cache)));

	if (list->id_position >= id)
		return 0;

	if (list->in_out_num >= ARRAY_SIZE(list->cache_id_tab))
		return 1;

	list->cache_id_tab[list->in_out_num] = id;
	list->in_out_num++;

	return 0;
}

int cache_mngt_list_caches(struct kcas_cache_list *list)
{
	list->in_out_num = 0;
	return ocf_mngt_cache_visit(cas_ctx, cache_mngt_list_caches_visitor, list);
}

int cache_mngt_interrupt_flushing(const char *cache_name, size_t name_len)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	cache_priv = ocf_cache_get_priv(cache);

	if (atomic_read(&cache_priv->flush_interrupt_enabled))
		ocf_mngt_cache_flush_interrupt(cache);

	ocf_mngt_cache_put(cache);

	return 0;

}

int cache_mngt_get_stats(struct kcas_get_stats *stats)
{
	int result;
	ocf_cache_t cache;
	ocf_core_t core = NULL;

	result = mngt_get_cache_by_id(cas_ctx, stats->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	if (stats->core_id == OCF_CORE_ID_INVALID &&
			stats->part_id == OCF_IO_CLASS_INVALID) {
		result = ocf_stats_collect_cache(cache, &stats->usage, &stats->req,
				&stats->blocks, &stats->errors);
		if (result)
			goto unlock;

	} else if (stats->part_id == OCF_IO_CLASS_INVALID) {
		result = get_core_by_id(cache, stats->core_id, &core);
		if (result)
			goto unlock;

		result = ocf_stats_collect_core(core, &stats->usage, &stats->req,
				&stats->blocks, &stats->errors);
		if (result)
			goto unlock;

	} else {
		if (stats->core_id == OCF_CORE_ID_INVALID) {
			result = ocf_stats_collect_part_cache(cache, stats->part_id,
					&stats->usage, &stats->req, &stats->blocks);
		} else {
			result = get_core_by_id(cache, stats->core_id, &core);
			if (result)
				goto unlock;

			result = ocf_stats_collect_part_core(core, stats->part_id,
					&stats->usage, &stats->req, &stats->blocks);
		}
	}

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_info(struct kcas_cache_info *info)
{
	uint32_t i, j;
	int result;
	ocf_cache_t cache;
	ocf_core_t core;
	const struct ocf_volume_uuid *uuid;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	result = ocf_cache_get_info(cache, &info->info);
	if (result)
		goto unlock;

	if (info->info.attached) {
		uuid = ocf_cache_get_uuid(cache);
		BUG_ON(!uuid);
		strlcpy(info->cache_path_name, uuid->data,
				min(sizeof(info->cache_path_name), uuid->size));

		switch (info->info.volume_type) {
		case BLOCK_DEVICE_VOLUME:
			info->metadata_mode = CAS_METADATA_MODE_NORMAL;
			break;
		case ATOMIC_DEVICE_VOLUME:
			info->metadata_mode = CAS_METADATA_MODE_ATOMIC;
			break;
		default:
			info->metadata_mode = CAS_METADATA_MODE_INVALID;
			break;
		}
	}

	/* Collect cores IDs */
	for (i = 0, j = 0; j < info->info.core_count &&
			i < OCF_CORE_MAX; i++) {
		if (get_core_by_id(cache, i, &core))
			continue;

		info->core_id[j] = i;
		j++;
	}

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_io_class_info(struct kcas_io_class *part)
{
	int result;
	uint16_t cache_id = part->cache_id;
	uint32_t io_class_id = part->class_id;
	ocf_cache_t cache;

	result = mngt_get_cache_by_id(cas_ctx, cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = ocf_cache_io_class_get_info(cache, io_class_id, &part->info);
	if (result)
		goto end;

end:
	ocf_mngt_cache_read_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_core_info(struct kcas_core_info *info)
{
	ocf_cache_t cache;
	ocf_core_t core;
	const struct ocf_volume_uuid *uuid;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if(result)
		goto put;

	result = get_core_by_id(cache, info->core_id, &core);
	if (result < 0) {
		result = OCF_ERR_CORE_NOT_AVAIL;
		goto unlock;
	}

	result = ocf_core_get_info(core, &info->info);
	if (result)
		goto unlock;

	uuid = ocf_core_get_uuid(core);

	if (uuid->data) {
		strlcpy(info->core_path_name, uuid->data,
				min(sizeof(info->core_path_name), uuid->size));
	}

	info->state = ocf_core_get_state(core);

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

static int cache_mngt_wait_for_rq_finish_visitor(ocf_core_t core, void *cntx)
{
	ocf_volume_t obj = ocf_core_get_volume(core);
	struct bd_object *bdobj = bd_object(obj);

	while (atomic64_read(&bdobj->pending_rqs))
		io_schedule();

	return 0;
}

void cache_mngt_wait_for_rq_finish(ocf_cache_t cache)
{
	ocf_core_visit(cache, cache_mngt_wait_for_rq_finish_visitor, NULL, true);
}

int cache_mngt_set_core_params(struct kcas_set_core_param *info)
{
	ocf_cache_t cache;
	ocf_core_t core = NULL;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	if (info->core_id != OCF_CORE_ID_INVALID) {
		result = get_core_by_id(cache, info->core_id, &core);
		if (result)
			goto out;
	}

	switch (info->param_id) {
	case core_param_seq_cutoff_threshold:
		result = cache_mngt_set_seq_cutoff_threshold(cache, core,
				info->param_value);
		break;
	case core_param_seq_cutoff_policy:
		result = cache_mngt_set_seq_cutoff_policy(cache, core,
				info->param_value);
		break;
	default:
		result = -EINVAL;
	}

out:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_core_params(struct kcas_get_core_param *info)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = get_core_by_id(cache, info->core_id, &core);
	if (result)
		goto out;

	switch (info->param_id) {
	case core_param_seq_cutoff_threshold:
		result = cache_mngt_get_seq_cutoff_threshold(core,
				&info->param_value);
		break;
	case core_param_seq_cutoff_policy:
		result = cache_mngt_get_seq_cutoff_policy(core,
				&info->param_value);
		break;
	default:
		result = -EINVAL;
	}

out:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_set_cache_params(struct kcas_set_cache_param *info)
{
	ocf_cache_t cache;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	switch (info->param_id) {
	case cache_param_cleaning_policy_type:
		result = cache_mngt_set_cleaning_policy(cache,
				info->param_value);
		break;

	case cache_param_cleaning_alru_wake_up_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_wake_up_time,
				info->param_value);
		break;
	case cache_param_cleaning_alru_stale_buffer_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_stale_buffer_time,
				info->param_value);
		break;
	case cache_param_cleaning_alru_flush_max_buffers:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_flush_max_buffers,
				info->param_value);
		break;
	case cache_param_cleaning_alru_activity_threshold:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_activity_threshold,
				info->param_value);
		break;

	case cache_param_cleaning_acp_wake_up_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_wake_up_time,
				info->param_value);
		break;
	case cache_param_cleaning_acp_flush_max_buffers:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_flush_max_buffers,
				info->param_value);
		break;
	case cache_param_promotion_policy_type:
		result = cache_mngt_set_promotion_policy(cache, info->param_value);
		break;
	case cache_param_promotion_nhit_insertion_threshold:
		result = cache_mngt_set_promotion_param(cache,
				ocf_nhit_insertion_threshold, info->param_value);
		break;
	case cache_param_promotion_nhit_trigger_threshold:
		result = cache_mngt_set_promotion_param(cache,
				ocf_nhit_trigger_threshold, info->param_value);
		break;
	default:
		result = -EINVAL;
	}

	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_cache_params(struct kcas_get_cache_param *info)
{
	ocf_cache_t cache;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	switch (info->param_id) {
	case cache_param_cleaning_policy_type:
		result = cache_mngt_get_cleaning_policy(cache,
				&info->param_value);
		break;

	case cache_param_cleaning_alru_wake_up_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_wake_up_time,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_stale_buffer_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_stale_buffer_time,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_flush_max_buffers:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_flush_max_buffers,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_activity_threshold:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_activity_threshold,
				&info->param_value);
		break;

	case cache_param_cleaning_acp_wake_up_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_wake_up_time,
				&info->param_value);
		break;
	case cache_param_cleaning_acp_flush_max_buffers:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_flush_max_buffers,
				&info->param_value);
		break;
	case cache_param_promotion_policy_type:
		result = cache_mngt_get_promotion_policy(cache, &info->param_value);
		break;
	case cache_param_promotion_nhit_insertion_threshold:
		result = cache_mngt_get_promotion_param(cache,
				ocf_nhit_insertion_threshold,
				&info->param_value);
		break;
	case cache_param_promotion_nhit_trigger_threshold:
		result = cache_mngt_get_promotion_param(cache,
				ocf_nhit_trigger_threshold,
				&info->param_value);
		break;
	default:
		result = -EINVAL;
	}

	ocf_mngt_cache_put(cache);
	return result;
}
