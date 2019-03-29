/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include  "cas_cache.h"

#define CAS_UPGRADE_DEBUG 0

#if 1 == CAS_UPGRADE_DEBUG
#define CAS_DEBUG_TRACE() \
	printk(KERN_INFO "[Upgrade] %s\n", __func__)

#define CAS_DEBUG_MSG(msg) \
	printk(KERN_INFO "[Upgrade] %s - %s\n", __func__, msg)

#define CAS_DEBUG_PARAM(format, ...) \
	printk(KERN_INFO "[Upgrade] %s - "format"\n", \
			__func__, ##__VA_ARGS__)
#else
#define CAS_DEBUG_TRACE()
#define CAS_DEBUG_MSG(msg)
#define CAS_DEBUG_PARAM(format, ...)
#endif

extern u32 max_writeback_queue_size;
extern u32 writeback_queue_unblock_size;
extern u32 metadata_layout;
extern u32 unaligned_io;
extern u32 seq_cut_off_mb;
extern u32 use_io_scheduler;

typedef int (*restore_callback_t) (struct cas_properties *cache_props);

static void _cas_upgrade_clear_state(void)
{
	in_upgrade = false;
}

static void _cas_upgrade_set_state(void)
{
	in_upgrade = true;
}

bool cas_upgrade_is_in_upgrade(void)
{
	return in_upgrade;
}

/*
 * Caches parameters to serialize
 * +------------+-------------------------------+---------------+
 * |Group	|		Key		|	Type	|
 * |------------|-------------------------------|---------------|
 * |cache	|	cache_id		|	uint	|
 * |cache	|	cache_path		|	string	|
 * |cache	|	cache_type		|	uint	|
 * |cache	|	cache_line_size		|	uint	|
 * |cache	|	cache_evp_policy	|	uint	|
 * |cache	|	cache_mode		|	uint	|
 * |cache	|	cache_seq_cutoff_thresh	|	uint	|
 * |cache	|	cache_seq_cutoff_policy	|	uint	|
 * |------------|-------------------------------|---------------|
 * |core	|	core_no			|	uint	|
 * |core	|	core_X_id		|	uint	|
 * |core	|	core_X_path		|	string	|
 * |core	|	core_X_type		|	uint	|
 * |------------|-------------------------------|---------------|
 * |flush	|	flush_cleaning_policy	|	uint	|
 * |flush	|	flush_wake_up_time	|	uint	|
 * |flush	|	flush_staleness_time	|	uint	|
 * |flush	|	flush_max_buffers	|	uint	|
 * |flush	|	flush_threshold		|	uint	|
 * |flush	|	flush_acp_wake_up_time	|	uint	|
 * |flush	|	flush_acp_max_buffers	|	uint	|
 * |------------|-------------------------------|---------------|
 * |io_class	|	io_class_no		|	uint	|
 * |io_class	|	io_class_X_name		|	string	|
 * |io_class	|	io_class_X_id		|	uint	|
 * |io_class	|	io_class_X_max		|	uint	|
 * |io_class	|	io_class_X_min		|	uint	|
 * |io_class	|	io_class_X_cache_mode	|	uint	|
 * |io_class	|	io_class_X_prio		|	uint	|
 * +------------+-------------------------------+---------------+
 *
 */

#define UPGRADE_IFACE_VERSION_STR "upgrade_iface_version"

#define CACHE_ID_STR "cache_id"
#define CACHE_PATH_STR "cache_path"
#define CACHE_LINE_SIZE_STR "cache_line_size"
#define CACHE_TYPE_STR "cache_type"
#define CACHE_MODE_STR "cache_mode"

#define CORE_NO_STR "core_no"
#define CORE_ID_STR "core_%lu_id"
#define CORE_PATH_STR "core_%lu_path"
#define CORE_SEQ_CUTOFF_THRESHOLD_STR "core_%lu_seq_cutoff_thresh"
#define CORE_SEQ_CUTOFF_POLICY_STR "core_%lu_seq_cutoff_policy"

#define CLEANING_POLICY_STR "flush_cleaning_policy"
#define CLEANING_ALRU_WAKEUP_TIME_STR "flush_wakeup_time"
#define CLEANING_ALRU_STALENESS_TIME_STR "flush_staleness_time"
#define CLEANING_ALRU_MAX_BUFFERS_STR "flush_max_buffers"
#define CLEANING_ALRU_TRESHOLD_STR "flush_threshold"
#define CLEANING_ACP_WAKEUP_TIME_STR "flush_acp_wakeup_time"
#define CLEANING_ACP_MAX_BUFFERS_STR "flush_acp_max_buffers"

#define IO_CLASS_NO_STR "io_class_no"
#define IO_CLASS_NAME_STR "io_class_%lu_name"
#define IO_CLASS_MIN_STR "io_class_%lu_min"
#define IO_CLASS_ID_STR "io_class_%lu_id"
#define IO_CLASS_MAX_STR "io_class_%lu_max"
#define IO_CLASS_PRIO_STR "io_class_%lu_prio"
#define IO_CLASS_CACHE_MODE_STR "io_class_%lu_cache_mode"

#define CAS_UPGRADE_IFACE_VERSION_19_03_00 190300
#define CAS_UPGRADE_IFACE_CURRENT_VERSION CAS_UPGRADE_IFACE_VERSION_19_03_00

static int _cas_upgrade_dump_cache_conf_main(ocf_cache_t cache,
	struct cas_properties *cache_props)
{
	int result = 0;

	CAS_DEBUG_TRACE();

	result = cas_properties_add_uint(cache_props, UPGRADE_IFACE_VERSION_STR,
			(uint64_t) CAS_UPGRADE_IFACE_CURRENT_VERSION,
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding interface version\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props, CACHE_ID_STR,
			(uint64_t) ocf_cache_get_id(cache),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding cache_id\n");
		return result;
	}

	result = cas_properties_add_string(cache_props, CACHE_PATH_STR,
			ocf_cache_get_uuid(cache)->data,
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding cache_path\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props, CACHE_LINE_SIZE_STR,
			(uint64_t) ocf_cache_get_line_size(cache),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding cache_line_size\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props, CACHE_TYPE_STR,
			(uint64_t) ocf_cache_get_type_id(cache),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT OCF_PREFIX_SHORT
				"Error during adding cache_type\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props, CACHE_MODE_STR,
			(uint64_t) ocf_cache_get_mode(cache),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT OCF_PREFIX_SHORT
				"Error during adding cache_mode\n");
		return result;
	}

	return result;
}

struct _ocf_core_visitor_ctx {
	int i;
	struct cas_properties *cache_props;
	int error;
};

int _cas_upgrade_core_visitor(ocf_core_t core, void *cntx)
{
	int result = 0;
	char *value = NULL;
	uint32_t core_idx = ocf_core_get_id(core);
	struct _ocf_core_visitor_ctx *core_visitor_ctx =
			(struct _ocf_core_visitor_ctx*) cntx;
	struct cas_properties *cache_props = core_visitor_ctx->cache_props;
	unsigned long core_no = 0;

	core_visitor_ctx->i++;
	core_no = core_visitor_ctx->i;

	value = kmalloc(sizeof(*value) * MAX_STR_LEN, GFP_KERNEL);
	if (value == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = snprintf(value, MAX_STR_LEN, CORE_ID_STR, core_no);
	if (result < 0)
		goto err;

	result = cas_properties_add_uint(cache_props, value, core_idx,
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT OCF_PREFIX_SHORT
				"Error during adding core id\n");
		goto err;
	}

	result = snprintf(value, MAX_STR_LEN, CORE_PATH_STR,
			core_no);
	if (result < 0)
		goto err;

	result = cas_properties_add_string(cache_props, value,
			ocf_core_get_uuid(core)->data, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT OCF_PREFIX_SHORT
				"Error during adding core path\n");
		goto err;
	}

	result = snprintf(value, MAX_STR_LEN, CORE_SEQ_CUTOFF_POLICY_STR, core_no);
	if (result < 0)
		goto err;

	result = cas_properties_add_uint(cache_props, value,
			(uint64_t) ocf_core_get_seq_cutoff_policy(core),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR "Error during adding core seq cutoff policy\n");
		goto err;
	}

	result = snprintf(value, MAX_STR_LEN, CORE_SEQ_CUTOFF_THRESHOLD_STR, core_no);
	if (result < 0)
		goto err;

	result = cas_properties_add_uint(cache_props, value,
			(uint64_t) ocf_core_get_seq_cutoff_threshold(core),
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR "Error during adding core seq cutoff threshold\n");
		goto err;
	}

err:
	kfree(value);
	core_visitor_ctx->error = result;
	return result;
}

static int _cas_upgrade_dump_cache_conf_cores(ocf_cache_t device,
	struct cas_properties *cache_props)
{
	int result = 0;
	struct _ocf_core_visitor_ctx core_visitor_ctx;
	char *value = NULL;

	CAS_DEBUG_TRACE();

	value = kmalloc(sizeof(*value) * MAX_STR_LEN, GFP_KERNEL);
	if (value == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = cas_properties_add_uint(cache_props, CORE_NO_STR,
			(uint64_t) ocf_cache_get_core_count(device),
			CAS_PROPERTIES_NON_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT OCF_PREFIX_SHORT
				"Error during adding cores number\n");
		goto err;
	}

	memset(&core_visitor_ctx, 0, sizeof(core_visitor_ctx));
	core_visitor_ctx.cache_props = cache_props;

	result |= ocf_core_visit(device, _cas_upgrade_core_visitor,
			&core_visitor_ctx, true);
	if (core_visitor_ctx.error) {
		result = core_visitor_ctx.error;
		goto err;
	}

	if (core_visitor_ctx.i > ocf_cache_get_core_count(device)) {
		result = -OCF_ERR_INVAL;
		goto err;
	}

err:
	kfree(value);
	return result;
}

static int _cas_upgrade_dump_cache_conf_flush(ocf_cache_t cache,
	struct cas_properties *cache_props)
{
	ocf_cache_id_t cache_id = ocf_cache_get_id(cache);
	uint32_t cleaning_type;
	uint32_t alru_thread_wakeup_time;
	uint32_t alru_stale_buffer_time;
	uint32_t alru_flush_max_buffers;
	uint32_t alru_activity_threshold;
	uint32_t acp_thread_wakeup_time;
	uint32_t acp_flush_max_buffers;
	int result = 0;

	CAS_DEBUG_TRACE();

	result |= cache_mng_get_cleaning_policy(cache_id, &cleaning_type);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_wake_up_time, &alru_thread_wakeup_time);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_stale_buffer_time, &alru_stale_buffer_time);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_flush_max_buffers, &alru_flush_max_buffers);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_activity_threshold, &alru_activity_threshold);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_acp,
			ocf_acp_wake_up_time, &acp_thread_wakeup_time);
	result |= cache_mng_get_cleaning_param(cache_id, ocf_cleaning_acp,
			ocf_acp_flush_max_buffers, &acp_flush_max_buffers);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Unable to get cleaning policy params\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props, CLEANING_POLICY_STR,
				cleaning_type, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding cleaning policy type\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ALRU_WAKEUP_TIME_STR,
			alru_thread_wakeup_time, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding alru wakeup time\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ALRU_STALENESS_TIME_STR,
			alru_stale_buffer_time, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding alru staleness time\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ALRU_MAX_BUFFERS_STR,
			alru_flush_max_buffers, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding alru max flush buffers\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ALRU_TRESHOLD_STR,
			alru_activity_threshold, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding alru flush threshold\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ACP_WAKEUP_TIME_STR,
			acp_thread_wakeup_time, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding acp wakeup time\n");
		return result;
	}

	result = cas_properties_add_uint(cache_props,
			CLEANING_ACP_MAX_BUFFERS_STR,
			acp_flush_max_buffers, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding acp max flush buffers\n");
		return result;
	}

	return result;
}

struct _cas_upgrade_dump_io_class_visit_ctx {
	struct cas_properties *cache_props;
	uint32_t io_class_counter;
	int error;
};

int _cas_upgrade_dump_io_class_visitor(ocf_cache_t cache,
		uint32_t io_class_id, void *ctx)
{
	int result = 0;
	struct ocf_io_class_info info;
	struct _cas_upgrade_dump_io_class_visit_ctx *io_class_visit_ctx =
			(struct _cas_upgrade_dump_io_class_visit_ctx*) ctx;
	char *key = NULL;
	struct cas_properties *cache_props = io_class_visit_ctx->cache_props;
	unsigned long io_class_counter;

	CAS_DEBUG_TRACE();

	key = kmalloc(sizeof(*key) * 4096, GFP_KERNEL);
	if (key == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = ocf_cache_io_class_get_info(cache, io_class_id, &info);
	if (result)
		goto error;

	io_class_visit_ctx->io_class_counter++;
	io_class_counter = io_class_visit_ctx->io_class_counter;

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_NAME_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_string(cache_props, key,
			info.name, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class name\n");
		goto error;
	}

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_MIN_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_uint(cache_props, key,
			info.min_size, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class min size\n");
		goto error;
	}

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_ID_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_uint(cache_props, key,
			io_class_id, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class id\n");
		goto error;
	}

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_MAX_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_uint(cache_props, key,
			info.max_size, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class max size\n");
		goto error;
	}

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_PRIO_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_uint(cache_props, key,
			info.priority, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class priority\n");
		goto error;
	}

	result = snprintf(key, MAX_STR_LEN,
			IO_CLASS_CACHE_MODE_STR, io_class_counter);
	if (result < 0)
		goto error;

	result = cas_properties_add_uint(cache_props, key,
			info.cache_mode, CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class cache mode\n");
		goto error;
	}

error:
	kfree(key);
	io_class_visit_ctx->error = result;
	return result;

}

static int _cas_upgrade_dump_cache_conf_io_class(ocf_cache_t cache,
		struct cas_properties *cache_props)
{
	int result = 0;
	struct _cas_upgrade_dump_io_class_visit_ctx  io_class_visit_ctx;

	CAS_DEBUG_TRACE();

	result = cas_properties_add_uint(cache_props, IO_CLASS_NO_STR, 0,
		CAS_PROPERTIES_NON_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class number\n");
		goto error_after_alloc_buffer;
	}

	memset(&io_class_visit_ctx, 0, sizeof(io_class_visit_ctx));
	io_class_visit_ctx.cache_props = cache_props;

	ocf_io_class_visit(cache, _cas_upgrade_dump_io_class_visitor,
			&io_class_visit_ctx);
	if (io_class_visit_ctx.error) {
		result = io_class_visit_ctx.error;
		goto error_after_alloc_buffer;
	}

	result = cas_properties_add_uint(cache_props, IO_CLASS_NO_STR,
			io_class_visit_ctx.io_class_counter,
			CAS_PROPERTIES_CONST);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during adding io class number\n");
		goto error_after_alloc_buffer;
	}

error_after_alloc_buffer:

	return result;
}

static int _cas_upgrade_dump_cache_conf(ocf_cache_t device,
	struct cas_properties *cache_props)
{
	int result = 0;

	CAS_DEBUG_TRACE();

	result = _cas_upgrade_dump_cache_conf_main(device, cache_props);
	if (result)
		return result;

	result = _cas_upgrade_dump_cache_conf_cores(device, cache_props);
	if (result)
		return result;

	result = _cas_upgrade_dump_cache_conf_flush(device, cache_props);
	if (result)
		return result;

	result = _cas_upgrade_dump_cache_conf_io_class(device, cache_props);
	if (result)
		return result;

	return result;
}

static void _cas_upgrade_destroy_props_array(
		struct cas_properties **caches_props_array, int count)
{
	int i;

	CAS_DEBUG_TRACE();

	for (i = 0; i < count ; i++) {
		if (caches_props_array[i] && !IS_ERR(caches_props_array[i]))
			cas_properties_destroy(caches_props_array[i]);
		caches_props_array[i] = NULL;
	}

}

static int _cas_upgrade_init_props_array(
		struct cas_properties **caches_props_array, int count)
{
	int i, result = 0;

	CAS_DEBUG_TRACE();

	for (i = 0; i < count ; i++) {
		caches_props_array[i] = cas_properties_create();
		if (IS_ERR(caches_props_array[i])) {
			result = PTR_ERR(caches_props_array[i]);
			break;
		}
	}

	if (result)
		_cas_upgrade_destroy_props_array(caches_props_array, i);

	return result;
}

struct _cas_cache_dump_conf_visitor_ctx {
	int i;
	struct cas_properties **caches_props_array;
	struct casdsk_props_conf *caches_serialized_conf;
	int error;

};

int _cas_upgrade_dump_cache_conf_visitor(ocf_cache_t cache, void *cntx)
{
	int result = 0;

	struct _cas_cache_dump_conf_visitor_ctx *cache_visit_ctx =
			(struct _cas_cache_dump_conf_visitor_ctx*) cntx;
	struct cas_properties **caches_props_array =
			cache_visit_ctx->caches_props_array;
	struct casdsk_props_conf *caches_serialized_conf =
			cache_visit_ctx->caches_serialized_conf;

	result = _cas_upgrade_dump_cache_conf(cache,
			caches_props_array[cache_visit_ctx->i]);
	if (result)
		goto error;

	result = cas_properties_serialize(
			caches_props_array[cache_visit_ctx->i],
			&caches_serialized_conf[cache_visit_ctx->i]);

error:
	cache_visit_ctx->i++;
	cache_visit_ctx->error = result;
	return result;
}

static int _cas_upgrade_dump_conf(void)
{
	int result = 0, i = 0;
	size_t caches_no = 0;
	struct casdsk_props_conf *caches_serialized_conf = NULL;
	struct _cas_cache_dump_conf_visitor_ctx cache_visit_ctx;
	struct cas_properties **caches_props_array;

	CAS_DEBUG_TRACE();

	caches_no = ocf_mngt_cache_get_count(cas_ctx);
	if (caches_no == 0)
		return 0;

	caches_props_array = kcalloc(caches_no,
			sizeof(*caches_props_array), GFP_KERNEL);
	if (caches_props_array == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	caches_serialized_conf = kcalloc(caches_no,
			sizeof(*caches_serialized_conf), GFP_KERNEL);
	if (caches_serialized_conf == NULL) {
		kfree(caches_props_array);
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = _cas_upgrade_init_props_array(caches_props_array, caches_no);
	if (result) {
		kfree(caches_props_array);
		kfree(caches_serialized_conf);
		return result;
	}

	/* Set up visitor context */
	memset(&cache_visit_ctx, 0, sizeof(cache_visit_ctx));
	cache_visit_ctx.caches_props_array = caches_props_array;
	cache_visit_ctx.caches_serialized_conf = caches_serialized_conf;

	result = ocf_mngt_cache_visit(cas_ctx, _cas_upgrade_dump_cache_conf_visitor,
			&cache_visit_ctx);
	if (result || cache_visit_ctx.error) {
		result |= cache_visit_ctx.error;
		goto err_after_init_props_array;
	}

	CAS_DEBUG_MSG("End of dump");

	casdisk_functions.casdsk_store_config(caches_no, caches_serialized_conf);

	CAS_DEBUG_MSG("Configuration stored to idisk");

err_after_init_props_array:
	if (result) {
		CAS_DEBUG_MSG("End of dump: ERROR");
		for (; i >= 0; i--)
			kfree(caches_serialized_conf[i].buffer);

		kfree(caches_serialized_conf);
		caches_no = 0;
	}
	_cas_upgrade_destroy_props_array(caches_props_array, caches_no);
	kfree(caches_props_array);
	return result;
}

int cas_upgrade_set_pt_and_flush_visitor_core(ocf_core_t core, void *cntx)
{
	int *result = (int*) cntx;
	ocf_volume_t vol;

	vol = ocf_core_get_volume(core);
	*result = casdisk_functions.casdsk_disk_set_pt(bd_object(vol)->dsk);

	return *result;
}

int _cas_upgrade_set_pt_and_flush_visitor_cache(ocf_cache_t cache, void *cntx)
{
	int *result = (int*) cntx;
	int cache_id = ocf_cache_get_id(cache);

	*result = cache_mng_set_cache_mode(cache_id, ocf_cache_mode_pt, false);
	if (*result)
		return *result;

	*result = cache_mng_flush_device(cache_id);
	if (*result)
		return *result;

	ocf_core_visit(cache, cas_upgrade_set_pt_and_flush_visitor_core,
			result, true);

	return *result;
}

static int _cas_upgrade_set_pt_and_flush(void)
{
	int result = 0, r = 0;

	CAS_DEBUG_TRACE();

	r = ocf_mngt_cache_visit_reverse(cas_ctx,
			_cas_upgrade_set_pt_and_flush_visitor_cache, &result);
	result |= r;

	return result;
}

int _cas_upgrade_stop_devices_visitor_wait(ocf_cache_t cache, void *cntx)
{
	cache_mng_wait_for_rq_finish(cache);

	return 0;
}

int _cas_upgrade_stop_devices_visitor_exit(ocf_cache_t cache, void *cntx)
{
	int *result = (int*) cntx;

	*result = cache_mng_exit_instance(ocf_cache_get_id(cache), true);

	return *result;
}

static int _cas_upgrade_stop_devices(void)
{
	int result = 0, r = 0;

	CAS_DEBUG_TRACE();

	r = ocf_mngt_cache_visit(cas_ctx, _cas_upgrade_stop_devices_visitor_wait,
			NULL);
	if (r)
		return r;

	r = ocf_mngt_cache_visit_reverse(cas_ctx,
			_cas_upgrade_stop_devices_visitor_exit, &result);
	result |= r;

	return result;
}

static int _cas_upgrade_restore_conf_main(struct cas_properties *cache_props,
		uint64_t *cache_id)
{
	int result = 0;
	uint64_t cache_mode, cache_line_size;
	uint64_t cache_type, version;
	char *cache_path = NULL;
	struct ocf_mngt_cache_config cfg;
	struct ocf_mngt_cache_device_config device_cfg;

	CAS_DEBUG_TRACE();

	cache_path = kzalloc(sizeof(*cache_path) * MAX_STR_LEN, GFP_KERNEL);
	if (cache_path == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = cas_properties_get_uint(cache_props, UPGRADE_IFACE_VERSION_STR,
			&version);
	if (result)
		goto error;

	result = cas_properties_get_uint(cache_props, CACHE_ID_STR, cache_id);
	if (result)
		goto error;

	result = cas_properties_get_string(cache_props, CACHE_PATH_STR,
			cache_path, MAX_STR_LEN);
	if (result)
		goto error;

	result = cas_properties_get_uint(cache_props, CACHE_TYPE_STR,
			&cache_type);
	if (result)
		goto error;

	result = cas_properties_get_uint(cache_props, CACHE_LINE_SIZE_STR,
			&cache_line_size);
	if (result)
		goto error;

	result = cas_properties_get_uint(cache_props, CACHE_MODE_STR,
			&cache_mode);
	if (result)
		goto error;

	if (cache_mode >= ocf_cache_mode_max)
		cache_mode = ocf_cache_mode_default;

	memset(&cfg, 0, sizeof(cfg));
	memset(&device_cfg, 0, sizeof(device_cfg));

	cfg.id = *cache_id;
	cfg.cache_mode = cache_mode;
	/* cfg.eviction_policy = TODO */
	cfg.cache_line_size = cache_line_size;
	cfg.metadata_layout = metadata_layout;
	cfg.pt_unaligned_io = !unaligned_io;
	cfg.use_submit_io_fast = !use_io_scheduler;
	cfg.locked = true;
	cfg.metadata_volatile = false;

	cfg.backfill.max_queue_size = max_writeback_queue_size;
	cfg.backfill.queue_unblock_size = writeback_queue_unblock_size;

	device_cfg.uuid.data = cache_path;
	device_cfg.uuid.size = strnlen(cache_path, MAX_STR_LEN) + 1;
	device_cfg.volume_type = cache_type;
	device_cfg.cache_line_size = cache_line_size;
	device_cfg.perform_test = true;
	device_cfg.force = false;

	result = cache_mng_init_instance(&cfg, &device_cfg, NULL);

error:
	kfree(cache_path);
	return result;
}

static int _cas_upgrade_restore_conf_core(struct cas_properties *cache_props,
		ocf_cache_t cache)
{
	int result = 0;
	unsigned long i = 0;
	uint64_t core_id, core_no, version;
	ocf_core_id_t core_id_int;

	char *core_path = NULL;
	char *key = NULL;
	struct ocf_mngt_core_config cfg = {};

	CAS_DEBUG_TRACE();

	key = kmalloc(sizeof(*key) * MAX_STR_LEN, GFP_KERNEL);
	if (key == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	core_path = kzalloc(sizeof(*core_path) * MAX_STR_LEN, GFP_KERNEL);
	if (core_path == NULL) {
		kfree(key);
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	result = cas_properties_get_uint(cache_props, UPGRADE_IFACE_VERSION_STR,
			&version);
	if (result)
		goto error;

	result = cas_properties_get_uint(cache_props, CORE_NO_STR, &core_no);
	if (result)
		goto error;

	for (i = 1; i < core_no + 1; i++) {
		result = snprintf(key, MAX_STR_LEN, CORE_PATH_STR, i);
		if (result < 0)
			goto error;

		result = cas_properties_get_string(cache_props, key,
			core_path, MAX_STR_LEN);
		if (result)
			goto error;

		result = snprintf(key, MAX_STR_LEN, CORE_ID_STR, i);
		if (result < 0)
			goto error;

		result = cas_properties_get_uint(cache_props, key, &core_id);
		if (result)
			goto error;

		core_id_int = core_id;

		cfg.try_add = 0;
		cfg.volume_type = BLOCK_DEVICE_VOLUME;
		cfg.core_id = core_id_int;
		cfg.cache_id = ocf_cache_get_id(cache);
		cfg.uuid.data = core_path;
		cfg.uuid.size = strnlen(core_path, MAX_STR_LEN) + 1;

		result = cache_mng_add_core_to_cache(&cfg, NULL);
		if (result)
			goto error;
	}

error:
	kfree(key);
	kfree(core_path);
	return result;
}

static int _cas_upgrade_restore_conf_flush(struct cas_properties *cache_props,
		ocf_cache_t cache)
{
	ocf_cache_id_t cache_id = ocf_cache_get_id(cache);
	uint64_t cleaning_type;
	uint64_t alru_thread_wakeup_time = OCF_ALRU_DEFAULT_WAKE_UP;
	uint64_t alru_stale_buffer_time = OCF_ALRU_DEFAULT_STALENESS_TIME;
	uint64_t alru_flush_max_buffers = OCF_ALRU_DEFAULT_FLUSH_MAX_BUFFERS;
	uint64_t alru_activity_threshold = OCF_ALRU_DEFAULT_ACTIVITY_THRESHOLD;
	uint64_t acp_thread_wakeup_time = OCF_ACP_DEFAULT_WAKE_UP;
	uint64_t acp_flush_max_buffers = OCF_ACP_DEFAULT_FLUSH_MAX_BUFFERS;
	uint64_t version;
	int result = 0;

	CAS_DEBUG_TRACE();

	result = cas_properties_get_uint(cache_props, UPGRADE_IFACE_VERSION_STR,
			&version);
	if (result)
		return result;

	result = cas_properties_get_uint(cache_props,
			CLEANING_POLICY_STR, &cleaning_type);
	if (result)
		return result;

	if (cleaning_type >= ocf_cleaning_max)
		cleaning_type = ocf_cleaning_default;

	/*
	 * CLEANING_ALRU_WAKEUP_TIME PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ALRU_WAKEUP_TIME_STR,
			&alru_thread_wakeup_time);
	if (result)
		return result;

	/*
	 * CLEANING_ALRU_STALENESS_TIME PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ALRU_STALENESS_TIME_STR,
			&alru_stale_buffer_time);
	if (result)
		return result;

	/*
	 * CLEANING_ALRU_MAX_BUFFERS PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ALRU_MAX_BUFFERS_STR,
			&alru_flush_max_buffers);
	if (result)
		return result;

	/*
	 * CLEANING_ALRU_TRESHOLD PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ALRU_TRESHOLD_STR,
			&alru_activity_threshold);
	if (result)
		return result;

	/*
	 * CLEANING_ACP_WAKEUP_TIME PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ACP_WAKEUP_TIME_STR,
			&acp_thread_wakeup_time);
	if (result)
		return result;

	/*
	 * CLEANING_ACP_MAX_BUFFERS PARAM
	 */

	result = cas_properties_get_uint(cache_props,
			CLEANING_ACP_MAX_BUFFERS_STR,
			&acp_flush_max_buffers);
	if (result)
		return result;

	result |= cache_mng_set_cleaning_policy(cache_id, cleaning_type);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_wake_up_time, alru_thread_wakeup_time);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_stale_buffer_time, alru_stale_buffer_time);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_flush_max_buffers, alru_flush_max_buffers);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_alru,
			ocf_alru_activity_threshold, alru_activity_threshold);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_acp,
			ocf_acp_wake_up_time, acp_thread_wakeup_time);
	result |= cache_mng_set_cleaning_param(cache_id, ocf_cleaning_acp,
			ocf_acp_flush_max_buffers, acp_flush_max_buffers);

	return result;
}

static int _cas_upgrade_restore_conf_io_class(
		struct cas_properties *cache_props, ocf_cache_t cache)
{
	int result = 0;
	unsigned long i = 0;
	uint64_t io_class_no, min_size, max_size, priority, cache_mode, part_id;
	char *name = NULL;
	char *key = NULL;
	struct kcas_io_classes *cfg;

	CAS_DEBUG_TRACE();

	key = kzalloc(sizeof(*key) * MAX_STR_LEN, GFP_KERNEL);
	if (key == NULL) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	name = kzalloc(sizeof(*name) * MAX_STR_LEN, GFP_KERNEL);
	if (name == NULL) {
		kfree(key);
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	cfg = kzalloc(KCAS_IO_CLASSES_SIZE, GFP_KERNEL);
	if (cfg == NULL) {
		kfree(key);
		kfree(name);
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	cfg->cache_id = ocf_cache_get_id(cache);

	result = cas_properties_get_uint(cache_props, IO_CLASS_NO_STR,
			&io_class_no);
	if (result)
		goto error_after_alloc_buffers;

	for (i = 1; i < io_class_no + 1; i++) {
		result = snprintf(key, MAX_STR_LEN, IO_CLASS_NAME_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_string(cache_props, key, name,
				MAX_STR_LEN);
		if (result)
			goto error_after_alloc_buffers;

		result = snprintf(key, MAX_STR_LEN, IO_CLASS_ID_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_uint(cache_props, key, &part_id);
		if (result)
			goto error_after_alloc_buffers;

		result = snprintf(key, MAX_STR_LEN, IO_CLASS_MIN_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_uint(cache_props, key, &min_size);
		if (result)
			goto error_after_alloc_buffers;

		result = snprintf(key, MAX_STR_LEN, IO_CLASS_MAX_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_uint(cache_props, key, &max_size);
		if (result)
			goto error_after_alloc_buffers;

		result = snprintf(key, MAX_STR_LEN, IO_CLASS_PRIO_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_uint(cache_props, key, &priority);
		if (result)
			goto error_after_alloc_buffers;

		result = snprintf(key, MAX_STR_LEN, IO_CLASS_CACHE_MODE_STR, i);
		if (result < 0)
			goto error_after_alloc_buffers;

		result = cas_properties_get_uint(cache_props, key, &cache_mode);
		if (result)
			goto error_after_alloc_buffers;

		result = env_strncpy(cfg->info[part_id].name, OCF_IO_CLASS_NAME_MAX,
				name, OCF_IO_CLASS_NAME_MAX);
		if (result)
			goto error_after_alloc_buffers;

		cfg->info[part_id].priority = (int16_t)priority;
		cfg->info[part_id].cache_mode = (ocf_cache_mode_t)cache_mode;
		cfg->info[part_id].max_size = (uint32_t)max_size;
		cfg->info[part_id].min_size = (uint32_t)min_size;
	}

	result = cache_mng_set_partitions(cfg);

error_after_alloc_buffers:
	kfree(key);
	kfree(name);
	kfree(cfg);
	return result;
}

static int _cas_upgrade_restore_cache(struct cas_properties *cache_props)
{
	int result = 0;
	uint64_t cache_id;
	ocf_cache_t cache;

	CAS_DEBUG_TRACE();

	result = _cas_upgrade_restore_conf_main(cache_props, &cache_id);
	if (result)
		return result;

	result = ocf_mngt_cache_get_by_id(cas_ctx, cache_id, &cache);
	if (result)
		return result;

	result = _cas_upgrade_restore_conf_core(cache_props, cache);
	if (result)
		goto error;

	result = _cas_upgrade_restore_conf_flush(cache_props, cache);
	if (result)
		goto error;

	result = _cas_upgrade_restore_conf_io_class(cache_props, cache);
	if (result)
		goto error;

error:
	ocf_mngt_cache_put(cache);
	return result;
}

int _cas_upgrade_restore_cache_mode_visitor(ocf_core_t core, void *cntx)
{
	int *result = (int*) cntx;
	ocf_volume_t vol;

	vol = ocf_core_get_volume(core);
	*result = casdisk_functions.casdsk_disk_clear_pt(bd_object(vol)->dsk);

	return *result;
}

static int _cas_upgrade_restore_cache_mode(struct cas_properties *cache_props)
{
	int result = 0;
	uint64_t cache_id, cache_mode;
	ocf_cache_t cache;

	CAS_DEBUG_TRACE();

	result = cas_properties_get_uint(cache_props, CACHE_ID_STR, &cache_id);
	if (result)
		return result;

	result = ocf_mngt_cache_get_by_id(cas_ctx, cache_id, &cache);
	if (result)
		return result;

	result = cas_properties_get_uint(cache_props, CACHE_MODE_STR,
			&cache_mode);
	if (result)
		goto error;

	if (ocf_cache_get_mode(cache) != cache_mode) {
		result = cache_mng_set_cache_mode(ocf_cache_get_id(cache),
				cache_mode, false);
		if (result)
			goto error;

		result |= ocf_core_visit(cache,
			_cas_upgrade_restore_cache_mode_visitor, &result, true);
	}

error:
	ocf_mngt_cache_put(cache);
	return result;
}

static int _cas_upgrade_restore_cache_after_error(
		struct cas_properties *cache_props)
{
	int result = 0;
	uint64_t cache_id;
	ocf_cache_t cache = NULL;

	CAS_DEBUG_TRACE();

	result = cas_properties_get_uint(cache_props, CACHE_ID_STR, &cache_id);
	if (result)
		return result;

	result = ocf_mngt_cache_get_by_id(cas_ctx, cache_id, &cache);
	if (result == -OCF_ERR_CACHE_NOT_EXIST) {
		result = _cas_upgrade_restore_cache(cache_props);
	} else if (result == 0) {
		result = _cas_upgrade_restore_cache_mode(cache_props);
		ocf_mngt_cache_put(cache);
	}

	return result;
}

static int _cas_upgrade_restore_configuration(
		struct casdsk_props_conf *caches_props_serialized_array,
		size_t caches_no, restore_callback_t restore_callback)
{
	int result = 0, i = 0;
	struct cas_properties **caches_props_array = NULL;

	CAS_DEBUG_TRACE();

	caches_props_array = kcalloc(caches_no, sizeof(*caches_props_array),
			GFP_KERNEL);
	if (!caches_props_array) {
		result = -OCF_ERR_NO_MEM;
		return result;
	}

	for (i = 0; i < caches_no; i++) {
		caches_props_array[i] = cas_properites_parse(
				&caches_props_serialized_array[i]);
		if (IS_ERR(caches_props_array[i])) {
			result = PTR_ERR(caches_props_array[i]);
			break;
		}

		if (caches_props_array[i]) {
#if 1 == CAS_UPGRADE_DEBUG
			cas_properties_print(caches_props_array[i]);
#endif
			result = restore_callback(caches_props_array[i]);
			if (result) {
				cas_properties_print(caches_props_array[i]);
				break;
			}
		}
	}

	_cas_upgrade_destroy_props_array(caches_props_array, caches_no);
	kfree(caches_props_array);
	return result;
}

struct casdsk_props_conf *caches_serialized_conf_init;
size_t caches_no_init;

int cas_upgrade_get_configuration(void)
{
	int result = 0;
	struct casdsk_props_conf *buffer = NULL;

	CAS_DEBUG_TRACE();

	caches_no_init = casdisk_functions.casdsk_get_stored_config(&buffer);
	if (caches_no_init == 0 || !buffer)
		return -KCAS_ERR_NO_STORED_CONF;

	_cas_upgrade_set_state();

	caches_serialized_conf_init = buffer;

	return result;
}

int cas_upgrade_check_ctx_visitor(ocf_cache_t cache, void *cntx)
{
	int result = ocf_cache_is_incomplete(cache);

	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Upgrade error. Cannot start upgrade in flight"
				" cache %d is in incomplete state\n",
				ocf_cache_get_id(cache));
	}

	return result;
}

static int _cas_cache_attached_check_visitor(ocf_cache_t cache, void *cntx)
{
	if (!ocf_cache_is_device_attached(cache)) {
		printk(KERN_ERR OCF_PREFIX_SHORT
			"Upgrade error. Cannot start upgrade in flight"
			" when cache drive is detached!\n");
		return 1;
	}

	return 0;
}

static int _cas_upgrade_check_ctx_state(void)
{
	if (ocf_mngt_core_pool_get_count(cas_ctx)) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Upgrade error. Cannot start upgrade in flight"
				" when core pool list is not empty\n");
		return -KCAS_ERR_CORE_POOL_NOT_EMPTY;
	}

	if (ocf_mngt_cache_visit(cas_ctx ,_cas_cache_attached_check_visitor,
				 NULL)) {
			return -KCAS_ERR_NO_CACHE_ATTACHED;
	}

	if (ocf_mngt_cache_visit(cas_ctx, cas_upgrade_check_ctx_visitor,
			NULL)) {
		return -OCF_ERR_CACHE_IN_INCOMPLETE_STATE;
	}

	return 0;
}

int cas_upgrade(void)
{
	int result = 0, result_rollback = 0;
	restore_callback_t restore_callback = NULL;

	CAS_DEBUG_TRACE();

	result = _cas_upgrade_check_ctx_state();
	if (result)
		return result;

	_cas_upgrade_set_state();

	result = _cas_upgrade_dump_conf();
	if (result)
		goto dump_err;

	result = _cas_upgrade_set_pt_and_flush();
	if (result) {
		restore_callback = _cas_upgrade_restore_cache_mode;
		goto upgrade_err;
	}

	result = _cas_upgrade_stop_devices();
	if (result) {
		restore_callback = _cas_upgrade_restore_cache_after_error;
		goto upgrade_err;
	}

	return 0;

upgrade_err:
	printk(KERN_ERR OCF_PREFIX_SHORT "Upgrade error. Start rollback");
	result_rollback = cas_upgrade_get_configuration();
	if (result_rollback != -KCAS_ERR_NO_STORED_CONF) {
		result_rollback = _cas_upgrade_restore_configuration(
				caches_serialized_conf_init, caches_no_init,
				restore_callback);
	} else {
		/* nothing to rool back - that's good */
		result_rollback = 0;
	}
	if (result_rollback) {
		/* rollback error */
		/* TODO: FIXME this path loses information about original cache
		   mode if we managed to switch to PT - configuration stored in
		   inteldisk will be freed before returning from this function.
		 */
		result = -KCAS_ERR_ROLLBACK;
	}

	casdisk_functions.casdsk_free_stored_config();

dump_err:
	_cas_upgrade_clear_state();
	return result;
}

int cas_upgrade_finish(void)
{
	int result = 0, rollback_result = 0;

	CAS_DEBUG_TRACE();

	result = _cas_upgrade_restore_configuration(caches_serialized_conf_init,
			caches_no_init, _cas_upgrade_restore_cache);
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Error during restoring configuration\n");
		rollback_result = _cas_upgrade_set_pt_and_flush();
		if (rollback_result)
			result = rollback_result;

		rollback_result = _cas_upgrade_stop_devices();
		if (rollback_result)
			result = rollback_result;
	} else {
		/*
		 * Remove configuration only in case when restoring finished
		 * successfully
		 */
		casdisk_functions.casdsk_free_stored_config();
	}

	_cas_upgrade_clear_state();

	return result;
}

static int _cas_upgrade_restore_noop(struct cas_properties *cache_props)
{
	return 0;
}

int cas_upgrade_verify(void)
{
	int result = 0;

	CAS_DEBUG_TRACE();

	result = _cas_upgrade_restore_configuration(caches_serialized_conf_init,
						    caches_no_init,
						    _cas_upgrade_restore_noop);

	return result;
}
