/*
* Copyright(c) 2012-2022 Intel Corporation
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

static inline int blkdev_can_hndl_bio(struct bio *bio)
{
	if (CAS_CHECK_BARRIER(bio)) {
		CAS_PRINT_RL(KERN_WARNING
			"special bio was sent, not supported!\n");
		return -ENOTSUPP;
	}

	return 0;
}

void blkdev_set_exported_object_flush_fua(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	ocf_volume_t core_vol = ocf_core_get_volume(core);
	ocf_volume_t cache_vol = ocf_cache_get_volume(cache);
	struct bd_object *bd_core_vol, *bd_cache_vol;
	struct request_queue *core_q, *exp_q, *cache_q;
	bool flush, fua;

	BUG_ON(!cache_vol);

	bd_core_vol = bd_object(core_vol);
	bd_cache_vol = bd_object(cache_vol);

	core_q = casdisk_functions.casdsk_disk_get_queue(bd_core_vol->dsk);
	exp_q = casdisk_functions.casdsk_exp_obj_get_queue(bd_core_vol->dsk);
	cache_q = casdisk_functions.casdsk_disk_get_queue(bd_cache_vol->dsk);

	flush = (CAS_CHECK_QUEUE_FLUSH(core_q) || CAS_CHECK_QUEUE_FLUSH(cache_q));
	fua = (CAS_CHECK_QUEUE_FUA(core_q) || CAS_CHECK_QUEUE_FUA(cache_q));

	cas_set_queue_flush_fua(exp_q, flush, fua);
}

static void blkdev_set_discard_properties(ocf_cache_t cache,
		struct request_queue *exp_q, struct block_device *cache_bd,
		struct block_device *core_bd, sector_t core_sectors)
{
	struct request_queue *core_q;
	struct request_queue *cache_q;

	core_q = bdev_get_queue(core_bd);
	cache_q = bdev_get_queue(cache_bd);

	CAS_QUEUE_FLAG_SET(QUEUE_FLAG_DISCARD, exp_q);

	CAS_SET_DISCARD_ZEROES_DATA(exp_q->limits, 0);
	if (core_q && blk_queue_discard(core_q)) {
		blk_queue_max_discard_sectors(exp_q, core_q->limits.max_discard_sectors);
		exp_q->limits.discard_alignment =
			bdev_discard_alignment(core_bd);
		exp_q->limits.discard_granularity =
			core_q->limits.discard_granularity;
	} else {
		blk_queue_max_discard_sectors(exp_q,
				min((uint64_t)core_sectors, (uint64_t)UINT_MAX));
		exp_q->limits.discard_granularity = ocf_cache_get_line_size(cache);
		exp_q->limits.discard_alignment = 0;
	}
}

/**
 * Map geometry of underlying (core) object geometry (sectors etc.)
 * to geometry of exported object.
 */
static int blkdev_core_set_geometry(struct casdsk_disk *dsk, void *private)
{
	ocf_core_t core;
	ocf_cache_t cache;
	ocf_volume_t core_vol;
	ocf_volume_t cache_vol;
	struct bd_object *bd_cache_vol;
	struct request_queue *core_q, *cache_q, *exp_q;
	struct block_device *core_bd, *cache_bd;
	sector_t sectors;
	const char *path;

	BUG_ON(!private);
	core = private;
	cache = ocf_core_get_cache(core);
	core_vol = ocf_core_get_volume(core);
	cache_vol = ocf_cache_get_volume(cache);
	BUG_ON(!cache_vol);

	bd_cache_vol = bd_object(cache_vol);
	path = ocf_volume_get_uuid(core_vol)->data;

	core_bd = casdisk_functions.casdsk_disk_get_blkdev(dsk);
	BUG_ON(!core_bd);

	cache_bd = casdisk_functions.casdsk_disk_get_blkdev(bd_cache_vol->dsk);
	BUG_ON(!cache_bd);

	core_q = cas_bdev_whole(core_bd)->bd_disk->queue;
	cache_q = cache_bd->bd_disk->queue;
	exp_q = casdisk_functions.casdsk_exp_obj_get_queue(dsk);

	sectors = ocf_volume_get_length(core_vol) >> SECTOR_SHIFT;

	set_capacity(casdisk_functions.casdsk_exp_obj_get_gendisk(dsk), sectors);

	cas_copy_queue_limits(exp_q, cache_q, core_q);

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

	blkdev_set_exported_object_flush_fua(core);

	blkdev_set_discard_properties(cache, exp_q, cache_bd, core_bd,
			sectors);

	return 0;
}

struct defer_bio_context {
	struct work_struct io_work;
	void (*cb)(struct bd_object *bvol, struct bio *bio);
	struct bd_object *bvol;
	struct bio *bio;
};

static void blkdev_defer_bio_work(struct work_struct *work)
{
	struct defer_bio_context *context;

	context = container_of(work, struct defer_bio_context, io_work);
	context->cb(context->bvol, context->bio);
	kfree(context);
}

static void blkdev_defer_bio(struct bd_object *bvol, struct bio *bio,
		void (*cb)(struct bd_object *bvol, struct bio *bio))
{
	struct defer_bio_context *context;

	BUG_ON(!bvol->expobj_wq);

	context = kmalloc(sizeof(*context), GFP_ATOMIC);
	if (!context) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
			CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	context->cb = cb;
	context->bio = bio;
	context->bvol = bvol;
	INIT_WORK(&context->io_work, blkdev_defer_bio_work);
	queue_work(bvol->expobj_wq, &context->io_work);
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

static void blkdev_complete_data(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;
	struct blk_data *master = io->priv2;
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

static int blkdev_handle_data_single(struct bd_object *bvol, struct bio *bio,
		struct blkdev_data_master_ctx *master_ctx)
{
	ocf_cache_t cache = ocf_volume_get_cache(bvol->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue = cache_priv->io_queues[smp_processor_id()];
	struct ocf_io *io;
	struct blk_data *data;
	uint64_t flags = CAS_BIO_OP_FLAGS(bio);
	int ret;

	data = cas_alloc_blk_data(bio_segments(bio), GFP_NOIO);
	if (!data) {
		CAS_PRINT_RL(KERN_CRIT "BIO data vector allocation error\n");
		return -ENOMEM;
	}

	blkdev_set_bio_data(data, bio);

	io = ocf_volume_new_io(bvol->front_volume, queue,
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

static void blkdev_handle_data(struct bd_object *bvol, struct bio *bio)
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

		error = blkdev_handle_data_single(bvol, split, &master_ctx);
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

static void blkdev_complete_discard(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;
	int result = map_cas_err_to_generic(error);

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(result));
	ocf_io_put(io);
}

static void blkdev_handle_discard(struct bd_object *bvol, struct bio *bio)
{
	ocf_cache_t cache = ocf_volume_get_cache(bvol->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue = cache_priv->io_queues[smp_processor_id()];
	struct ocf_io *io;

	io = ocf_volume_new_io(bvol->front_volume, queue,
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

static void blkdev_handle_bio_noflush(struct bd_object *bvol, struct bio *bio)
{
	if (CAS_IS_DISCARD(bio))
		blkdev_handle_discard(bvol, bio);
	else
		blkdev_handle_data(bvol, bio);
}

static void blkdev_complete_flush(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;
	struct bd_object *bvol = io->priv2;
	int result = map_cas_err_to_generic(error);

	ocf_io_put(io);

	if (CAS_BIO_BISIZE(bio) == 0 || error) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(result));
		return;
	}

	if (in_interrupt())
		blkdev_defer_bio(bvol, bio, blkdev_handle_bio_noflush);
	else
		blkdev_handle_bio_noflush(bvol, bio);
}

static void blkdev_handle_flush(struct bd_object *bvol, struct bio *bio)
{
	ocf_cache_t cache = ocf_volume_get_cache(bvol->front_volume);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_queue_t queue = cache_priv->io_queues[smp_processor_id()];
	struct ocf_io *io;

	io = ocf_volume_new_io(bvol->front_volume, queue, 0, 0, OCF_WRITE, 0,
			CAS_SET_FLUSH(0));
	if (!io) {
		CAS_PRINT_RL(KERN_CRIT
			"Out of memory. Ending IO processing.\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ocf_io_set_cmpl(io, bio, bvol, blkdev_complete_flush);

	ocf_volume_submit_flush(io);
}

static void blkdev_handle_bio(struct bd_object *bvol, struct bio *bio)
{
	if (CAS_IS_SET_FLUSH(CAS_BIO_OP_FLAGS(bio)))
		blkdev_handle_flush(bvol, bio);
	else
		blkdev_handle_bio_noflush(bvol, bio);
}

static void blkdev_submit_bio(struct bd_object *bvol, struct bio *bio)
{
	if (blkdev_can_hndl_bio(bio)) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(-ENOTSUPP));
		return;
	}

	if (in_interrupt())
		blkdev_defer_bio(bvol, bio, blkdev_handle_bio);
	else
		blkdev_handle_bio(bvol, bio);
}

static void blkdev_core_submit_bio(struct casdsk_disk *dsk,
		struct bio *bio, void *private)
{
	ocf_core_t core = private;
	struct bd_object *bvol;

	BUG_ON(!core);

	bvol = bd_object(ocf_core_get_volume(core));

	blkdev_submit_bio(bvol, bio);
}

static struct casdsk_exp_obj_ops kcas_core_exp_obj_ops = {
	.set_geometry = blkdev_core_set_geometry,
	.submit_bio = blkdev_core_submit_bio,
};

static int blkdev_cache_set_geometry(struct casdsk_disk *dsk, void *private)
{
	ocf_cache_t cache;
	ocf_volume_t volume;
	struct bd_object *bvol;
	struct request_queue *cache_q, *exp_q;
	struct block_device *bd;
	sector_t sectors;

	BUG_ON(!private);
	cache = private;
	volume = ocf_cache_get_volume(cache);

	bvol = bd_object(volume);

	bd = casdisk_functions.casdsk_disk_get_blkdev(bvol->dsk);
	BUG_ON(!bd);

	cache_q = bd->bd_disk->queue;
	exp_q = casdisk_functions.casdsk_exp_obj_get_queue(dsk);

	sectors = ocf_volume_get_length(volume) >> SECTOR_SHIFT;

	set_capacity(casdisk_functions.casdsk_exp_obj_get_gendisk(dsk), sectors);

	cas_copy_queue_limits(exp_q, cache_q, cache_q);

	blk_stack_limits(&exp_q->limits, &cache_q->limits, 0);

	/* We don't want to receive splitted requests*/
	CAS_SET_QUEUE_CHUNK_SECTORS(exp_q, 0);

	cas_set_queue_flush_fua(exp_q, CAS_CHECK_QUEUE_FLUSH(cache_q),
			CAS_CHECK_QUEUE_FUA(cache_q));

	return 0;
}

static void blkdev_cache_submit_bio(struct casdsk_disk *dsk,
		struct bio *bio, void *private)
{
	ocf_cache_t cache = private;
	struct bd_object *bvol;

	BUG_ON(!cache);

	bvol = bd_object(ocf_cache_get_volume(cache));

	blkdev_submit_bio(bvol, bio);
}

static struct casdsk_exp_obj_ops kcas_cache_exp_obj_ops = {
	.set_geometry = blkdev_cache_set_geometry,
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

static int kcas_volume_create_exported_object(ocf_volume_t volume,
		const char *name, void *priv, struct casdsk_exp_obj_ops *ops)
{
	struct bd_object *bvol = bd_object(volume);
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(volume);
	struct casdsk_disk *dsk;
	int result;

	dsk = casdisk_functions.casdsk_disk_claim(uuid->data, priv);
	if (dsk != bvol->dsk) {
		result = -KCAS_ERR_SYSTEM;
		goto end;
	}

	bvol->expobj_wq = alloc_workqueue("expobj_wq_%s",
			WQ_MEM_RECLAIM | WQ_HIGHPRI, 0,
			name);
	if (!bvol->expobj_wq) {
		result = -ENOMEM;
		goto end;
	}

	result = casdisk_functions.casdsk_exp_obj_create(dsk, name,
			THIS_MODULE, ops);
	if (result) {
		destroy_workqueue(bvol->expobj_wq);
		goto end;
	}

	bvol->expobj_valid = true;

end:
	if (result) {
		printk(KERN_ERR "Cannot create exported object %s. Error code %d\n",
				name, result);
	}
	return result;
}

static int kcas_volume_destroy_exported_object(ocf_volume_t volume)
{
	struct bd_object *bvol;
	int result;

	BUG_ON(!volume);

	bvol = bd_object(volume);
	BUG_ON(!bvol);

	if (!bvol->expobj_valid)
		return 0;

	result = casdisk_functions.casdsk_exp_obj_lock(bvol->dsk);
	if (result == -EBUSY)
		return -KCAS_ERR_DEV_PENDING;
	else if (result)
		return result;

	result = casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
	if (result)
		goto out;

	bvol->expobj_valid = false;
	destroy_workqueue(bvol->expobj_wq);

out:
	casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);

	return result;
}

/**
 * @brief this routine actually adds /dev/casM-N inode
 */
static int kcas_volume_activate_exported_object(ocf_volume_t volume,
		struct casdsk_exp_obj_ops *ops)
{
	struct bd_object *bvol = bd_object(volume);
	int result;

	result = casdisk_functions.casdsk_exp_obj_activate(bvol->dsk);
	if (result == -EEXIST)
		result = -KCAS_ERR_FILE_EXISTS;

	return result;
}

int kcas_core_create_exported_object(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	ocf_volume_t volume = ocf_core_get_volume(core);
	struct bd_object *bvol = bd_object(volume);
	char dev_name[DISK_NAME_LEN];

	snprintf(dev_name, DISK_NAME_LEN, "cas%s-%s",
			get_cache_id_string(cache),
			get_core_id_string(core));

	bvol->front_volume = ocf_core_get_front_volume(core);

	return kcas_volume_create_exported_object(volume, dev_name, core,
			&kcas_core_exp_obj_ops);
}

int kcas_core_destroy_exported_object(ocf_core_t core)
{
	ocf_volume_t volume = ocf_core_get_volume(core);

	return kcas_volume_destroy_exported_object(volume);
}

int kcas_core_activate_exported_object(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	ocf_volume_t volume = ocf_core_get_volume(core);
	int result;

	result = kcas_volume_activate_exported_object(volume,
			&kcas_core_exp_obj_ops);
	if (result) {
		printk(KERN_ERR "Cannot activate exported object, %s.%s. "
				"Error code %d\n", ocf_cache_get_name(cache),
				ocf_core_get_name(core), result);
	}

	return result;
}

int kcas_cache_create_exported_object(ocf_cache_t cache)
{
	ocf_volume_t volume = ocf_cache_get_volume(cache);
	struct bd_object *bvol = bd_object(volume);
	char dev_name[DISK_NAME_LEN];

	snprintf(dev_name, DISK_NAME_LEN, "cas-cache-%s",
			get_cache_id_string(cache));

	bvol->front_volume = ocf_cache_get_front_volume(cache);

	return kcas_volume_create_exported_object(volume, dev_name, cache,
			&kcas_cache_exp_obj_ops);
}

int kcas_cache_destroy_exported_object(ocf_cache_t cache)
{
	ocf_volume_t volume = ocf_cache_get_volume(cache);

	return kcas_volume_destroy_exported_object(volume);
}

int kcas_cache_activate_exported_object(ocf_cache_t cache)
{
	ocf_volume_t volume = ocf_cache_get_volume(cache);
	int result;

	result = kcas_volume_activate_exported_object(volume,
			&kcas_cache_exp_obj_ops);
	if (result) {
		printk(KERN_ERR "Cannot activate cache %s exported object. "
				"Error code %d\n", ocf_cache_get_name(cache),
				result);
	}

	return result;
}

static int kcas_core_lock_exported_object(ocf_core_t core, void *cntx)
{
	int result;
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));

	if (!bvol->expobj_valid)
		return 0;

	result = casdisk_functions.casdsk_exp_obj_lock(bvol->dsk);

	if (-EBUSY == result) {
		printk(KERN_WARNING "Stopping %s failed - device in use\n",
			casdisk_functions.casdsk_exp_obj_get_gendisk(bvol->dsk)->disk_name);
		return -KCAS_ERR_DEV_PENDING;
	} else if (result) {
		printk(KERN_WARNING "Stopping %s failed - device unavailable\n",
			casdisk_functions.casdsk_exp_obj_get_gendisk(bvol->dsk)->disk_name);
		return -OCF_ERR_CORE_NOT_AVAIL;
	}

	bvol->expobj_locked = true;

	return 0;
}


static int kcas_core_unlock_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(ocf_core_get_volume(core));

	if (bvol->expobj_locked) {
		casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);
		bvol->expobj_locked = false;
	}

	return 0;
}

static int kcas_core_stop_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));
	int ret;

	if (bvol->expobj_valid) {
		BUG_ON(!bvol->expobj_locked);

		printk(KERN_INFO "Stopping device %s\n",
			casdisk_functions.casdsk_exp_obj_get_gendisk(bvol->dsk)->disk_name);

		ret = casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
		if (!ret) {
			bvol->expobj_valid = false;
			destroy_workqueue(bvol->expobj_wq);
		}
	}

	if (bvol->expobj_locked) {
		casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);
		bvol->expobj_locked = false;
	}

	return 0;
}

static int kcas_core_free_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(ocf_core_get_volume(core));

	casdisk_functions.casdsk_exp_obj_free(bvol->dsk);

	return 0;
}

int kcas_cache_destroy_all_core_exported_objects(ocf_cache_t cache)
{
	int result;

	/* Try lock exported objects */
	result = ocf_core_visit(cache, kcas_core_lock_exported_object, NULL,
			true);
	if (result) {
		/* Failure, unlock already locked exported objects */
		ocf_core_visit(cache, kcas_core_unlock_exported_object, NULL,
				true);
		return result;
	}

	ocf_core_visit(cache, kcas_core_stop_exported_object, NULL, true);
	ocf_core_visit(cache, kcas_core_free_exported_object, NULL, true);

	return 0;
}
