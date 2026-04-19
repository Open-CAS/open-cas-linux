/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "utils/cas_err.h"

static void blkdev_set_bio_data(struct blk_data *data, struct bio *bio)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 14, 0)
	struct bio_vec *bvec;
	uint32_t iter = 0, i = 0;

	bio_for_each_segment(bvec, bio, iter) {
		BUG_ON(i >= data->size);
		data->vec[i] = *bvec;
		i++;
	}
#else
	struct bio_vec bvec;
	struct bvec_iter iter;
	uint32_t i = 0;

	bio_for_each_segment(bvec, bio, iter) {
		BUG_ON(i >= data->size);
		data->vec[i] = bvec;
		i++;
	}
#endif
}

static void blkdev_set_exported_object_flush_fua(ocf_core_t core,
		struct cas_exp_obj *exp_obj)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	ocf_volume_t core_vol = ocf_core_get_volume(core);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(core_vol);
	struct request_queue *core_q, *exp_q;
	bool flush, fua;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	core_q = cas_disk_get_queue(priv_bottom->dsk);
	exp_q = cas_exp_obj_get_queue(exp_obj);

	flush = (CAS_CHECK_QUEUE_FLUSH(core_q) ||
			cache_priv->device_properties.flush);
	fua = (CAS_CHECK_QUEUE_FUA(core_q) || cache_priv->device_properties.fua);

	cas_set_queue_flush_fua(exp_q, flush, fua);
}

static void blkdev_set_discard_properties(ocf_cache_t cache,
		struct request_queue *exp_q, struct block_device *core_bd,
		sector_t core_sectors)
{
	struct request_queue *core_q;

	core_q = bdev_get_queue(core_bd);

	cas_set_discard_flag(exp_q);

	CAS_SET_DISCARD_ZEROES_DATA(exp_q->limits, 0);
	if (core_q && cas_has_discard_support(core_bd)) {
		cas_queue_max_discard_sectors(exp_q,
				core_q->limits.max_discard_sectors);
		exp_q->limits.discard_alignment =
			bdev_discard_alignment(core_bd);
		exp_q->limits.discard_granularity =
			core_q->limits.discard_granularity;
	} else {
		cas_queue_max_discard_sectors(exp_q,
				min((uint64_t)core_sectors, (uint64_t)UINT_MAX));
		exp_q->limits.discard_granularity = ocf_cache_get_line_size(cache);
		exp_q->limits.discard_alignment = 0;
	}
}

/**
 * Map geometry of underlying (core) object geometry (sectors etc.)
 * to geometry of exported object.
 */
static int blkdev_core_set_geometry(struct cas_exp_obj *exp_obj)
{
	ocf_core_t core = cas_exp_obj_get_priv(exp_obj);
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_volume_t core_vol = ocf_core_get_volume(core);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(core_vol);
	struct block_device *core_bd = priv_bottom->btm_bd;
	const char *path = ocf_volume_get_uuid(core_vol)->data;
	struct request_queue *core_q = cas_disk_get_queue(priv_bottom->dsk);
	struct request_queue *exp_q = cas_exp_obj_get_queue(exp_obj);
	sector_t sectors = ocf_volume_get_length(core_vol) >> SECTOR_SHIFT;

	set_capacity(cas_exp_obj_get_gendisk(exp_obj), sectors);

	cas_copy_queue_limits(exp_q, &cache_priv->device_properties.queue_limits,
			core_q);

	if (exp_q->limits.logical_block_size >
		core_q->limits.logical_block_size) {
		printk(KERN_ERR "Cache device logical sector size is "
			"greater than core device %s logical sector size.\n",
			path);
		return -KCAS_ERR_UNALIGNED;
	}

	blk_stack_limits(&exp_q->limits, &core_q->limits, 0);

	/* We don't want to receive splitted requests*/
	CAS_SET_QUEUE_CHUNK_SECTORS(exp_q, 0);

	blkdev_set_exported_object_flush_fua(core, exp_obj);

	blkdev_set_discard_properties(cache, exp_q, core_bd, sectors);

	cas_queue_set_nonrot(exp_q);

	return 0;
}

static int blkdev_core_set_queue_limits(struct cas_exp_obj *exp_obj,
		cas_queue_limits_t *lim)
{
	ocf_core_t core = cas_exp_obj_get_priv(exp_obj);
	ocf_cache_t cache = ocf_core_get_cache(core);
	ocf_volume_t core_vol = ocf_core_get_volume(core);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(core_vol);
	struct request_queue *core_q = cas_disk_get_queue(priv_bottom->dsk);
	bool flush, fua;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);


	flush = (CAS_CHECK_QUEUE_FLUSH(core_q) ||
			cache_priv->device_properties.flush);
	fua = (CAS_CHECK_QUEUE_FUA(core_q) ||
			cache_priv->device_properties.fua);

	memset(lim, 0, sizeof(cas_queue_limits_t));

	if (flush)
		CAS_SET_QUEUE_LIMIT(lim, CAS_BLK_FEAT_WRITE_CACHE);

	if (fua)
		CAS_SET_QUEUE_LIMIT(lim, CAS_BLK_FEAT_FUA);

	return 0;
}

struct defer_bio_context {
	struct work_struct io_work;
	void (*cb)(struct cas_priv_top *priv_top, struct bio *bio);
	struct cas_priv_top *priv_top;
	struct bio *bio;
};

static void blkdev_defer_bio_work(struct work_struct *work)
{
	struct defer_bio_context *context;

	context = container_of(work, struct defer_bio_context, io_work);
	context->cb(context->priv_top, context->bio);
	kfree(context);
}

static void blkdev_defer_bio(struct cas_priv_top *priv_top, struct bio *bio,
		void (*cb)(struct cas_priv_top *priv_top, struct bio *bio))
{
	struct defer_bio_context *context;

	BUG_ON(!priv_top->expobj_wq);

	context = kmalloc(sizeof(*context), GFP_ATOMIC);
	if (!context) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
			CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	context->cb = cb;
	context->bio = bio;
	context->priv_top = priv_top;
	INIT_WORK(&context->io_work, blkdev_defer_bio_work);
	queue_work(priv_top->expobj_wq, &context->io_work);
}

static void blkdev_complete_data_master(struct blk_data *master, int error)
{
	int result;

	master->error = master->error ?: error;

	if (atomic_dec_return(&master->master_remaining))
		return;

	cas_generic_end_io_acct(master->bio, master->start_time);

	result = map_cas_err_to_generic(master->error);
	CAS_BIO_ENDIO(master->bio, master->master_size,
			CAS_ERRNO_TO_BLK_STS(result));

	cas_free_blk_data(master);
}

static void blkdev_complete_data(ocf_io_t io, void *priv1, void *priv2,
		int error)
{
	struct bio *bio = priv1;
	struct blk_data *master = priv2;
	struct blk_data *data = ocf_io_get_data(io);

	ocf_io_put(io);
	if (data != master)
		cas_free_blk_data(data);
	if (bio != master->bio)
		bio_put(bio);

	blkdev_complete_data_master(master, error);
}

struct blkdev_data_master_ctx {
	struct blk_data *data;
	struct bio *bio;
	uint32_t master_size;
	unsigned long long start_time;
};

static int blkdev_handle_data_single(struct cas_priv_top *priv_top,
		struct bio *bio, struct blkdev_data_master_ctx *master_ctx)
{
	ocf_cache_t cache = ocf_volume_get_cache(priv_top->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue;
	ocf_io_t io;
	struct blk_data *data;
	uint64_t flags = CAS_BIO_OP_FLAGS(bio);
	int ret;

	queue = cache_priv->io_queues[raw_smp_processor_id()];

	data = cas_alloc_blk_data(bio_segments(bio), GFP_NOIO);
	if (!data) {
		CAS_PRINT_RL(KERN_CRIT "BIO data vector allocation error\n");
		return -ENOMEM;
	}

	blkdev_set_bio_data(data, bio);

	io = ocf_volume_new_io(priv_top->front_volume, queue,
			CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
			CAS_BIO_BISIZE(bio), (bio_data_dir(bio) == READ) ?
					OCF_READ : OCF_WRITE,
			cas_cls_classify(cache, bio), CAS_CLEAR_FLUSH(flags));

	if (!io) {
		printk(KERN_CRIT "Out of memory. Ending IO processing.\n");
		cas_free_blk_data(data);
		return -ENOMEM;
	}

	ret = ocf_io_set_data(io, data, 0);
	if (ret < 0) {
		ocf_io_put(io);
		cas_free_blk_data(data);
		return -EINVAL;
	}

	if (!master_ctx->data) {
		atomic_set(&data->master_remaining, 1);
		data->bio = master_ctx->bio;
		data->master_size = master_ctx->master_size;
		data->start_time = master_ctx->start_time;
		master_ctx->data = data;
	}

	atomic_inc(&master_ctx->data->master_remaining);

	ocf_io_set_cmpl(io, bio, master_ctx->data, blkdev_complete_data);

	ocf_volume_submit_io(io);

	return 0;
}

static void blkdev_handle_data(struct cas_priv_top *priv_top, struct bio *bio)
{
	const uint32_t max_io_sectors = (32*MiB) >> SECTOR_SHIFT;
	const uint32_t align_sectors = (128*KiB) >> SECTOR_SHIFT;
	struct bio *split = NULL;
	uint32_t sectors, to_submit;
	int error;
	struct blkdev_data_master_ctx master_ctx = {
		.bio = bio,
		.master_size = CAS_BIO_BISIZE(bio),
	};

	if (unlikely(CAS_BIO_BISIZE(bio) == 0)) {
		CAS_PRINT_RL(KERN_ERR
			"Not able to handle empty BIO, flags = "
			CAS_BIO_OP_FLAGS_FORMAT "\n",  CAS_BIO_OP_FLAGS(bio));
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(-EINVAL));
		return;
	}

	master_ctx.start_time = cas_generic_start_io_acct(bio);
	for (sectors = bio_sectors(bio); sectors > 0;) {
		if (sectors <= max_io_sectors) {
			split = bio;
			sectors = 0;
		} else {
			to_submit = max_io_sectors -
					CAS_BIO_BISECTOR(bio) % align_sectors;
			split = cas_bio_split(bio, to_submit);
			sectors -= to_submit;
		}

		error = blkdev_handle_data_single(priv_top, split, &master_ctx);
		if (error)
			goto err;
	}

	blkdev_complete_data_master(master_ctx.data, 0);

	return;

err:
	if (split != bio)
		bio_put(split);
	if (master_ctx.data)
		blkdev_complete_data_master(master_ctx.data, error);
	else
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(error));
}

static void blkdev_complete_discard(ocf_io_t io, void *priv1, void *priv2,
		int error)
{
	struct bio *bio = priv1;
	int result = map_cas_err_to_generic(error);

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(result));
	ocf_io_put(io);
}

static void blkdev_handle_discard(struct cas_priv_top *priv_top,
		struct bio *bio)
{
	ocf_cache_t cache = ocf_volume_get_cache(priv_top->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue;
	ocf_io_t io;

	queue = cache_priv->io_queues[raw_smp_processor_id()];

	io = ocf_volume_new_io(priv_top->front_volume, queue,
			CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
			CAS_BIO_BISIZE(bio), OCF_WRITE, 0, 0);
	if (!io) {
		CAS_PRINT_RL(KERN_CRIT
			"Out of memory. Ending IO processing.\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ocf_io_set_cmpl(io, bio, NULL, blkdev_complete_discard);

	ocf_volume_submit_discard(io);
}

static void blkdev_handle_bio_noflush(struct cas_priv_top *priv_top,
		struct bio *bio)
{
	if (CAS_IS_DISCARD(bio))
		blkdev_handle_discard(priv_top, bio);
	else
		blkdev_handle_data(priv_top, bio);
}

static void blkdev_complete_flush(ocf_io_t io, void *priv1, void *priv2,
		int error)
{
	struct bio *bio = priv1;
	struct cas_priv_top *priv_top = priv2;
	int result = map_cas_err_to_generic(error);

	ocf_io_put(io);

	if (CAS_BIO_BISIZE(bio) == 0 || error) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(result));
		return;
	}

	blkdev_defer_bio(priv_top, bio, blkdev_handle_bio_noflush);
}

static void blkdev_handle_flush(struct cas_priv_top *priv_top, struct bio *bio)
{
	ocf_cache_t cache = ocf_volume_get_cache(priv_top->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue;
	ocf_io_t io;

	queue = cache_priv->io_queues[raw_smp_processor_id()];

	io = ocf_volume_new_io(priv_top->front_volume, queue, 0, 0,
			OCF_WRITE, 0, CAS_SET_FLUSH(0));
	if (!io) {
		CAS_PRINT_RL(KERN_CRIT
			"Out of memory. Ending IO processing.\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ocf_io_set_cmpl(io, bio, priv_top, blkdev_complete_flush);

	ocf_volume_submit_flush(io);
}

static void blkdev_handle_bio(struct cas_priv_top *priv_top, struct bio *bio)
{
	if (CAS_IS_SET_FLUSH(CAS_BIO_OP_FLAGS(bio)))
		blkdev_handle_flush(priv_top, bio);
	else
		blkdev_handle_bio_noflush(priv_top, bio);
}

static void blkdev_submit_bio(struct cas_priv_top *priv_top, struct bio *bio)
{
	if (in_interrupt())
		blkdev_defer_bio(priv_top, bio, blkdev_handle_bio);
	else
		blkdev_handle_bio(priv_top, bio);
}

static void blkdev_core_submit_bio(struct cas_exp_obj *exp_obj, struct bio *bio)
{
	ocf_core_t core = cas_exp_obj_get_priv(exp_obj);
	struct cas_priv_top *priv_top = cas_get_priv_top(core);

	blkdev_submit_bio(priv_top, bio);
}

static struct cas_exp_obj_ops kcas_core_exp_obj_ops = {
	.set_geometry = blkdev_core_set_geometry,
	.set_queue_limits = blkdev_core_set_queue_limits,
	.submit_bio = blkdev_core_submit_bio,
};

static int blkdev_cache_set_geometry(struct cas_exp_obj *exp_obj)
{
	ocf_cache_t cache = cas_exp_obj_get_priv(exp_obj);
	ocf_volume_t volume = ocf_cache_get_volume(cache);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(volume);
	struct block_device *bd = priv_bottom->btm_bd;
	struct request_queue *cache_q = bd->bd_disk->queue;
	struct request_queue *exp_q = cas_exp_obj_get_queue(exp_obj);
	sector_t sectors = ocf_volume_get_length(volume) >> SECTOR_SHIFT;

	set_capacity(cas_exp_obj_get_gendisk(exp_obj), sectors);

	cas_copy_queue_limits(exp_q, &cache_q->limits, cache_q);
	cas_cache_set_no_merges_flag(cache_q);

	blk_stack_limits(&exp_q->limits, &cache_q->limits, 0);

	/* We don't want to receive splitted requests*/
	CAS_SET_QUEUE_CHUNK_SECTORS(exp_q, 0);

	cas_set_queue_flush_fua(exp_q, CAS_CHECK_QUEUE_FLUSH(cache_q),
			CAS_CHECK_QUEUE_FUA(cache_q));

	return 0;
}

static int blkdev_cache_set_queue_limits(struct cas_exp_obj *exp_obj,
		cas_queue_limits_t *lim)
{
	ocf_cache_t cache = cas_exp_obj_get_priv(exp_obj);
	ocf_volume_t volume = ocf_cache_get_volume(cache);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(volume);
	struct block_device *bd = priv_bottom->btm_bd;
	struct request_queue *cache_q = bd->bd_disk->queue;

	memset(lim, 0, sizeof(cas_queue_limits_t));

	if (CAS_CHECK_QUEUE_FLUSH(cache_q))
		CAS_SET_QUEUE_LIMIT(lim, CAS_BLK_FEAT_WRITE_CACHE);

	if (CAS_CHECK_QUEUE_FUA(cache_q))
		CAS_SET_QUEUE_LIMIT(lim, CAS_BLK_FEAT_FUA);

	return 0;
}

static void blkdev_cache_submit_bio(struct cas_exp_obj *exp_obj,
		struct bio *bio)
{
	ocf_cache_t cache = cas_exp_obj_get_priv(exp_obj);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	blkdev_submit_bio(&cache_priv->priv_top, bio);
}

static struct cas_exp_obj_ops kcas_cache_exp_obj_ops = {
	.set_geometry = blkdev_cache_set_geometry,
	.set_queue_limits = blkdev_cache_set_queue_limits,
	.submit_bio = blkdev_cache_submit_bio,
};

/****************************************
 * Exported object management functions *
 ****************************************/


static const char *get_cache_id_string(ocf_cache_t cache)
{
	return ocf_cache_get_name(cache) + sizeof("cache") - 1;
}

static const char *get_core_id_string(ocf_core_t core)
{
	return ocf_core_get_name(core) + sizeof("core") - 1;
}

static int kcas_create_exported_object(struct cas_priv_top *priv_top,
		struct cas_disk *dsk, const char *name, void *priv,
		struct cas_exp_obj_ops *ops)
{
	struct cas_exp_obj *exp_obj;
	int result = 0;

	priv_top->expobj_wq = alloc_workqueue("expobj_wq_%s",
			WQ_MEM_RECLAIM | WQ_HIGHPRI, 0,
			name);
	if (!priv_top->expobj_wq) {
		result = -ENOMEM;
		goto end;
	}

	exp_obj = cas_exp_obj_create(dsk, name, THIS_MODULE, ops, priv);
	if (IS_ERR_OR_NULL(exp_obj)) {
		destroy_workqueue(priv_top->expobj_wq);
		result = PTR_ERR(exp_obj);
		goto end;
	}

	priv_top->exp_obj = exp_obj;
	priv_top->expobj_valid = true;

end:
	if (result) {
		printk(KERN_ERR "Cannot create exported object %s. Error code %d\n",
				name, result);
	}
	return result;
}

static int kcas_volume_destroy_exported_object(struct cas_priv_top *priv_top)
{
	int result;

	if (!priv_top->expobj_valid)
		return 0;

	result = cas_exp_obj_lock(priv_top->exp_obj);
	if (result == -EBUSY)
		return -KCAS_ERR_DEV_PENDING;
	else if (result)
		return result;

	result = cas_exp_obj_dismantle(priv_top->exp_obj);
	if (result)
		goto err;

	priv_top->expobj_valid = false;
	destroy_workqueue(priv_top->expobj_wq);

	cas_exp_obj_unlock(priv_top->exp_obj);
	cas_exp_obj_destroy(priv_top->exp_obj);

	return 0;

err:
	cas_exp_obj_unlock(priv_top->exp_obj);

	return result;
}

/**
 * @brief this routine actually adds /dev/casM-N inode
 */
int kcas_core_create_exported_object(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cas_priv_top *priv_top;
	ocf_volume_t volume = ocf_core_get_volume(core);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(volume);
	char dev_name[DISK_NAME_LEN];
	int result;

	priv_top = vzalloc(sizeof(*priv_top));
	if (!priv_top)
		return -ENOMEM;

	snprintf(dev_name, DISK_NAME_LEN, "cas%s-%s",
			get_cache_id_string(cache),
			get_core_id_string(core));

	priv_top->front_volume = ocf_core_get_front_volume(core);
	ocf_core_set_priv(core, priv_top);

	result = kcas_create_exported_object(priv_top, priv_bottom->dsk,
			dev_name, core, &kcas_core_exp_obj_ops);
	if (result) {
		ocf_core_set_priv(core, NULL);
		vfree(priv_top);
		return result;
	}

	return 0;
}

int kcas_core_destroy_exported_object(ocf_core_t core)
{
	struct cas_priv_top *priv_top = cas_get_priv_top(core);
	int result;

	result = kcas_volume_destroy_exported_object(priv_top);
	if (result)
		return result;

	ocf_core_set_priv(core, NULL);
	vfree(priv_top);

	return 0;
}

int kcas_cache_create_exported_object(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct cas_priv_top *priv_top = &cache_priv->priv_top;
	ocf_volume_t volume = ocf_cache_get_volume(cache);
	struct cas_priv_bottom *priv_bottom = cas_get_priv_bottom(volume);
	char dev_name[DISK_NAME_LEN];

	snprintf(dev_name, DISK_NAME_LEN, "cas-cache-%s",
			get_cache_id_string(cache));

	priv_top->front_volume = ocf_cache_get_front_volume(cache);

	return kcas_create_exported_object(priv_top, priv_bottom->dsk, dev_name,
			cache, &kcas_cache_exp_obj_ops);
}

int kcas_cache_destroy_exported_object(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct cas_priv_top *priv_top = &cache_priv->priv_top;

	return kcas_volume_destroy_exported_object(priv_top);
}

static char *_get_disk_name(struct cas_exp_obj *exp_obj)
{
	return cas_exp_obj_get_gendisk(exp_obj)->disk_name;
}

int kcas_cache_destroy_all_core_exported_objects(ocf_cache_t cache)
{
	struct cas_priv_top *priv_top;
	ocf_core_t core;
	int result = 0;

	/* Try lock exported objects */
	ocf_core_for_each(core, cache, true) {
		priv_top = cas_get_priv_top(core);

		if (!priv_top->expobj_valid)
			continue;

		result = cas_exp_obj_lock(priv_top->exp_obj);
		if (-EBUSY == result) {
			printk(KERN_WARNING
				"Stopping %s failed - device in use\n",
				_get_disk_name(priv_top->exp_obj));
			result = -KCAS_ERR_DEV_PENDING;
			break;
		} else if (result) {
			printk(KERN_WARNING
				"Stopping %s failed - device unavailable\n",
				_get_disk_name(priv_top->exp_obj));
			result = -OCF_ERR_CORE_NOT_AVAIL;
			break;
		}

		priv_top->expobj_locked = true;
	}

	if (result) {
		/* Failure, unlock already locked exported objects */
		ocf_core_for_each(core, cache, true) {
			priv_top = cas_get_priv_top(core);
			if (priv_top->expobj_locked) {
				cas_exp_obj_unlock(priv_top->exp_obj);
				priv_top->expobj_locked = false;
			}
		}
		return result;
	}

	ocf_core_for_each(core, cache, true) {
		priv_top = cas_get_priv_top(core);
		if (priv_top->expobj_valid) {
			printk(KERN_INFO "Stopping device %s\n",
				_get_disk_name(priv_top->exp_obj));

			result = cas_exp_obj_dismantle(priv_top->exp_obj);
			if (!result) {
				priv_top->expobj_valid = false;
				destroy_workqueue(priv_top->expobj_wq);
			}
		}

		if (priv_top->expobj_locked) {
			cas_exp_obj_unlock(priv_top->exp_obj);
			priv_top->expobj_locked = false;
		}
	}

	ocf_core_for_each(core, cache, true) {
		priv_top = cas_get_priv_top(core);
		cas_exp_obj_destroy(priv_top->exp_obj);
	}

	return 0;
}
