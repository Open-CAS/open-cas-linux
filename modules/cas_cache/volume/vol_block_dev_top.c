/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils/cas_err.h"

static void _blockdev_set_bio_data(struct blk_data *data, struct bio *bio)
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

static inline unsigned long long _blockdev_start_io_acct(struct bio *bio)
{
	struct gendisk *gd = CAS_BIO_GET_DEV(bio);

	return cas_generic_start_io_acct(gd->queue, bio, &gd->part0);
}

static inline void _blockdev_end_io_acct(struct bio *bio,
		unsigned long start_time)
{
	struct gendisk *gd = CAS_BIO_GET_DEV(bio);

	cas_generic_end_io_acct(gd->queue, bio, &gd->part0, start_time);
}

static inline int _blkdev_can_hndl_bio(struct bio *bio)
{
	if (CAS_CHECK_BARRIER(bio)) {
		CAS_PRINT_RL(KERN_WARNING
			"special bio was sent, not supported!\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-EOPNOTSUPP));
		return -ENOTSUPP;
	}

	return 0;
}

void _blockdev_set_exported_object_flush_fua(ocf_core_t core)
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

static void _blockdev_set_discard_properties(ocf_cache_t cache,
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
		exp_q->limits.discard_granularity = queue_logical_block_size(exp_q);
		exp_q->limits.discard_alignment = 0;
	}
}

/**
 * Map geometry of underlying (core) object geometry (sectors etc.)
 * to geometry of exported object.
 */
static int _blockdev_set_geometry(struct casdsk_disk *dsk, void *private)
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

	core_q = core_bd->bd_contains->bd_disk->queue;
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

	_blockdev_set_exported_object_flush_fua(core);

	_blockdev_set_discard_properties(cache, exp_q, cache_bd, core_bd,
			sectors);

	return 0;
}

struct defer_bio_context {
	struct work_struct io_work;
	void (*cb)(ocf_core_t core, struct bio *bio);
	ocf_core_t core;
	struct bio *bio;
};

static void _blockdev_defer_bio_work(struct work_struct *work)
{
	struct defer_bio_context *context;

	context = container_of(work, struct defer_bio_context, io_work);
	context->cb(context->core, context->bio);
	kfree(context);
}

static void _blockdev_defer_bio(ocf_core_t core, struct bio *bio,
	void (*cb)(ocf_core_t core, struct bio *bio))
{
	struct defer_bio_context *context;
	ocf_volume_t volume = ocf_core_get_volume(core);
	struct bd_object *bvol = bd_object(volume);

	BUG_ON(!bvol->expobj_wq);

	context = kmalloc(sizeof(*context), GFP_ATOMIC);
	if (!context) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
			CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	context->cb = cb;
	context->bio = bio;
	context->core = core;
	INIT_WORK(&context->io_work, _blockdev_defer_bio_work);
	queue_work(bvol->expobj_wq, &context->io_work);
}

static void block_dev_complete_data(struct ocf_io *io, int error)
{
	struct blk_data *data = ocf_io_get_data(io);
	struct bio *bio = data->master_io_req;

	_blockdev_end_io_acct(bio, data->start_time);

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(error));
	ocf_io_put(io);
	cas_free_blk_data(data);
}

static void _blockdev_handle_data(ocf_core_t core, struct bio *bio)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	struct ocf_io *io;
	struct blk_data *data;
	uint64_t flags = CAS_BIO_OP_FLAGS(bio);
	int ret;

	cache = ocf_core_get_cache(core);
	cache_priv = ocf_cache_get_priv(cache);

	if (unlikely(CAS_BIO_BISIZE(bio) == 0)) {
		CAS_PRINT_RL(KERN_ERR
			"Not able to handle empty BIO, flags = "
			CAS_BIO_OP_FLAGS_FORMAT "\n",  CAS_BIO_OP_FLAGS(bio));
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-EINVAL));
		return;
	}

	data = cas_alloc_blk_data(bio_segments(bio), GFP_NOIO);
	if (!data) {
		CAS_PRINT_RL(KERN_CRIT "BIO data vector allocation error\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	_blockdev_set_bio_data(data, bio);

	data->master_io_req = bio;

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
			CAS_BIO_BISIZE(bio), (bio_data_dir(bio) == READ) ?
					OCF_READ : OCF_WRITE,
			cas_cls_classify(cache, bio), CAS_CLEAR_FLUSH(flags));

	if (!io) {
		printk(KERN_CRIT "Out of memory. Ending IO processing.\n");
		cas_free_blk_data(data);
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ret = ocf_io_set_data(io, data, 0);
	if (ret < 0) {
		ocf_io_put(io);
		cas_free_blk_data(data);
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-EINVAL));
		return;
	}

	ocf_io_set_cmpl(io, NULL, NULL, block_dev_complete_data);
	data->start_time = _blockdev_start_io_acct(bio);

	ocf_core_submit_io(io);
}

static void block_dev_complete_discard(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(error));
	ocf_io_put(io);
}

static void _blockdev_handle_discard(ocf_core_t core, struct bio *bio)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct ocf_io *io;

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
			CAS_BIO_BISIZE(bio), OCF_WRITE, 0, 0);

	if (!io) {
		CAS_PRINT_RL(KERN_CRIT
			"Out of memory. Ending IO processing.\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ocf_io_set_cmpl(io, bio, NULL, block_dev_complete_discard);

	ocf_core_submit_discard(io);
}

static void _blockdev_handle_bio_noflush(ocf_core_t core, struct bio *bio)
{
	if (CAS_IS_DISCARD(bio))
		_blockdev_handle_discard(core, bio);
	else
		_blockdev_handle_data(core, bio);
}

static void block_dev_complete_flush(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;
	ocf_core_t core = io->priv2;

	ocf_io_put(io);

	if (CAS_BIO_BISIZE(bio) == 0 || error) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(error));
		return;
	}

	if (in_interrupt())
		_blockdev_defer_bio(core, bio, _blockdev_handle_bio_noflush);
	else
		_blockdev_handle_bio_noflush(core, bio);
}

static void _blkdev_handle_flush(ocf_core_t core, struct bio *bio)
{
	struct ocf_io *io;
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			0, 0, OCF_WRITE, 0, CAS_SET_FLUSH(0));
	if (!io) {
		CAS_PRINT_RL(KERN_CRIT
			"Out of memory. Ending IO processing.\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return;
	}

	ocf_io_set_cmpl(io, bio, core, block_dev_complete_flush);

	ocf_core_submit_flush(io);
}

static void _blockdev_handle_bio(ocf_core_t core, struct bio *bio)
{
	if (CAS_IS_SET_FLUSH(CAS_BIO_OP_FLAGS(bio)))
		_blkdev_handle_flush(core, bio);
	else
		_blockdev_handle_bio_noflush(core, bio);
}

static void _blockdev_submit_bio(struct casdsk_disk *dsk,
		struct bio *bio, void *private)
{
	ocf_core_t core = private;

	BUG_ON(!core);

	if (_blkdev_can_hndl_bio(bio)) {
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio),
				CAS_ERRNO_TO_BLK_STS(-ENOTSUPP));
		return;
	}

	if (in_interrupt())
		_blockdev_defer_bio(core, bio, _blockdev_handle_bio);
	else
		_blockdev_handle_bio(core, bio);
}

static struct casdsk_exp_obj_ops _blockdev_exp_obj_ops = {
	.set_geometry = _blockdev_set_geometry,
	.submit_bio = _blockdev_submit_bio,
};

/**
 * @brief this routine actually adds /dev/casM-N inode
 */
int block_dev_activate_exported_object(ocf_core_t core)
{
	int ret;
	ocf_volume_t obj = ocf_core_get_volume(core);
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct bd_object *bvol = bd_object(obj);

	if (!cas_upgrade_is_in_upgrade()) {
		ret = casdisk_functions.casdsk_exp_obj_activate(bvol->dsk);
		if (-EEXIST == ret)
			ret = KCAS_ERR_FILE_EXISTS;
	} else {
		ret = casdisk_functions.casdsk_disk_attach(bvol->dsk, THIS_MODULE,
				&_blockdev_exp_obj_ops);
	}

	if (ret) {
		printk(KERN_ERR "Cannot activate exported object, %s.%s. "
				"Error code %d\n", ocf_cache_get_name(cache),
				ocf_core_get_name(core), ret);
	}

	return ret;
}

static const char *get_cache_id_string(ocf_cache_t cache)
{
	return ocf_cache_get_name(cache) + sizeof("cache") - 1;
}

static const char *get_core_id_string(ocf_core_t core)
{
	return ocf_core_get_name(core) + sizeof("core") - 1;
}

int block_dev_create_exported_object(ocf_core_t core)
{
	ocf_volume_t obj = ocf_core_get_volume(core);
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct bd_object *bvol = bd_object(obj);
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(obj);
	char dev_name[DISK_NAME_LEN];
	struct casdsk_disk *dsk;
	int result;

	snprintf(dev_name, DISK_NAME_LEN, "cas%s-%s",
			get_cache_id_string(cache),
			get_core_id_string(core));

	dsk = casdisk_functions.casdsk_disk_claim(uuid->data, core);
	if (dsk != bvol->dsk) {
		result = -KCAS_ERR_SYSTEM;
		goto end;
	}

	if (cas_upgrade_is_in_upgrade()) {
		bvol->expobj_valid = true;
		return 0;
	}

	bvol->expobj_wq = alloc_workqueue("expobj_wq%s-%s",
			WQ_MEM_RECLAIM | WQ_HIGHPRI, 0,
			get_cache_id_string(cache),
			get_core_id_string(core));
	if (!bvol->expobj_wq) {
		result = -ENOMEM;
		goto end;
	}

	result = casdisk_functions.casdsk_exp_obj_create(dsk, dev_name,
			THIS_MODULE, &_blockdev_exp_obj_ops);
	if (result) {
		destroy_workqueue(bvol->expobj_wq);
		goto end;
	}

	bvol->expobj_valid = true;

end:
	if (result) {
		printk(KERN_ERR "Cannot create exported object %s. Error code %d\n",
				dev_name, result);
	}
	return result;
}

int block_dev_destroy_exported_object(ocf_core_t core)
{
	int ret = 0;
	ocf_volume_t obj = ocf_core_get_volume(core);
	struct bd_object *bvol = bd_object(obj);

	if (!bvol->expobj_valid)
		return 0;

	destroy_workqueue(bvol->expobj_wq);

	ret = casdisk_functions.casdsk_exp_obj_lock(bvol->dsk);
	if (ret) {
		if (-EBUSY == ret)
			ret = -KCAS_ERR_DEV_PENDING;
		return ret;
	}

	ret = casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
	if (!ret)
		bvol->expobj_valid = false;

	casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);

	return ret;
}

static int _block_dev_lock_exported_object(ocf_core_t core, void *cntx)
{
	int result;
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));

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

static int _block_dev_unlock_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));

	if (bvol->expobj_locked) {
		casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);
		bvol->expobj_locked = false;
	}

	return 0;
}

static int _block_dev_stop_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));
	int ret;

	if (bvol->expobj_valid) {
		BUG_ON(!bvol->expobj_locked);

		printk(KERN_INFO "Stopping device %s\n",
			casdisk_functions.casdsk_exp_obj_get_gendisk(bvol->dsk)->disk_name);

		ret = casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
		if (!ret)
			bvol->expobj_valid = false;
	}

	if (bvol->expobj_locked) {
		casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);
		bvol->expobj_locked = false;
	}

	return 0;
}

static int _block_dev_free_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));

	casdisk_functions.casdsk_exp_obj_free(bvol->dsk);
	return 0;
}

int block_dev_destroy_all_exported_objects(ocf_cache_t cache)
{
	int result;

	/* Try lock exported objects */
	result = ocf_core_visit(cache, _block_dev_lock_exported_object, NULL,
			true);
	if (result) {
		/* Failure, unlock already locked exported objects */
		ocf_core_visit(cache, _block_dev_unlock_exported_object, NULL,
				true);
		return result;
	}

	ocf_core_visit(cache, _block_dev_stop_exported_object, NULL, true);

	return ocf_core_visit(cache, _block_dev_free_exported_object, NULL,
			true);
}
