/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils/cas_err.h"

#define BLK_RQ_POS(rq) (CAS_BIO_BISECTOR((rq)->bio))
#define BLK_RQ_BYTES(rq) blk_rq_bytes(rq)

static inline void _blockdev_end_request_all(struct request *rq, int error)
{
	CAS_END_REQUEST_ALL(rq, CAS_ERRNO_TO_BLK_STS(
					map_cas_err_to_generic(error)));
}

static inline bool _blockdev_can_handle_rq(struct request *rq)
{
	int error = 0;

	if (unlikely(!cas_is_rq_type_fs(rq)))
		error = __LINE__;

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 1, 0)
	if (unlikely(blk_bidi_rq(rq)))
		error = __LINE__;
#endif

	if (error != 0) {
		CAS_PRINT_RL(KERN_ERR "%s cannot handle request (ERROR %d)\n",
			rq->rq_disk->disk_name, error);
		return false;
	}

	return true;
}

static void _blockdev_set_bio_data(struct blk_data *data, struct bio *bio)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 14, 0)
	struct bio_vec *bvec;
	uint32_t i = 0;

	bio_for_each_segment(bvec, bio, i) {
		BUG_ON(i >= data->size);
		data->vec[i] = *bvec;
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

static inline void _blockdev_start_io_acct(struct bio *bio)
{
	struct gendisk *gd = CAS_BIO_GET_DEV(bio);

	cas_generic_start_io_acct(gd->queue, bio_data_dir(bio),
			bio_sectors(bio), &gd->part0);
}

static inline void _blockdev_end_io_acct(struct bio *bio,
		unsigned long start_time)
{
	struct gendisk *gd = CAS_BIO_GET_DEV(bio);

	cas_generic_end_io_acct(gd->queue, bio_data_dir(bio),
			&gd->part0, start_time);
}

void block_dev_start_bio_fast(struct ocf_io *io)
{
	struct blk_data *data = ocf_io_get_data(io);
	struct bio *bio = data->master_io_req;

	_blockdev_start_io_acct(bio);
}

void block_dev_complete_bio_fast(struct ocf_io *io, int error)
{
	struct blk_data *data = ocf_io_get_data(io);
	struct bio *bio = data->master_io_req;

	_blockdev_end_io_acct(bio, data->start_time);

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(error));
	ocf_io_put(io);
	cas_free_blk_data(data);
}

void block_dev_complete_bio_discard(struct ocf_io *io, int error)
{
	struct bio *bio = io->priv1;

	CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(error));
	ocf_io_put(io);
}

void block_dev_complete_rq(struct ocf_io *io, int error)

{
	struct blk_data *data = ocf_io_get_data(io);
	struct request *rq = data->master_io_req;

	_blockdev_end_request_all(rq, error);
	ocf_io_put(io);
	cas_free_blk_data(data);
}

void block_dev_complete_sub_rq(struct ocf_io *io, int error)
{
	struct blk_data *data = ocf_io_get_data(io);
	struct ocf_io *master = data->master_io_req;
	struct blk_data *master_data = ocf_io_get_data(master);

	if (error)
		master_data->error = error;

	if (atomic_dec_return(&master_data->master_remaining) == 0) {
		_blockdev_end_request_all(master_data->master_io_req,
				master_data->error);
		cas_free_blk_data(master_data);
		ocf_io_put(master);
	}

	ocf_io_put(io);
	cas_free_blk_data(data);
}

void block_dev_complete_flush(struct ocf_io *io, int error)
{
	struct request *rq = io->priv1;

	_blockdev_end_request_all(rq, error);
	ocf_io_put(io);
}

bool _blockdev_is_request_barier(struct request *rq)
{
	struct bio *i_bio = rq->bio;

	for_each_bio(i_bio) {
		if (CAS_CHECK_BARRIER(i_bio))
			return true;
	}
	return false;
}

static int _blockdev_alloc_many_requests(ocf_core_t core,
		struct list_head *list, struct request *rq,
		struct ocf_io *master)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	int error = 0;
	int flags = 0;
	struct bio *bio;
	struct ocf_io *sub_io;
	struct blk_data *master_data = ocf_io_get_data(master);
	struct blk_data *data;

	INIT_LIST_HEAD(list);

	/* Go over requests and allocate sub requests */
	bio = rq->bio;
	for_each_bio(bio) {
		/* Setup BIO flags */
		if (CAS_IS_WRITE_FLUSH_FUA(CAS_BIO_OP_FLAGS(bio))) {
			/* FLUSH and FUA */
			flags = CAS_WRITE_FLUSH_FUA;
		} else if (CAS_IS_WRITE_FUA(CAS_BIO_OP_FLAGS(bio))) {
			/* FUA */
			flags = CAS_WRITE_FUA;
		} else if (CAS_IS_WRITE_FLUSH(CAS_BIO_OP_FLAGS(bio))) {
			/* FLUSH - It shall be handled in request handler */
			error = -EINVAL;
			break;
		} else {
			flags = 0;
		}

		data = cas_alloc_blk_data(bio_segments(bio), GFP_NOIO);
		if (!data) {
			CAS_PRINT_RL(KERN_CRIT "BIO data vector allocation error\n");
			error = -ENOMEM;
			break;
		}

		_blockdev_set_bio_data(data, bio);

		data->master_io_req = master;

		sub_io = ocf_core_new_io(core,
				cache_priv->io_queues[smp_processor_id()],
				CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
				CAS_BIO_BISIZE(bio), (bio_data_dir(bio) == READ) ?
						OCF_READ : OCF_WRITE,
				cas_cls_classify(cache, bio), flags);

		if (!sub_io) {
			cas_free_blk_data(data);
			error = -ENOMEM;
			break;
		}

		data->io = sub_io;

		error = ocf_io_set_data(sub_io, data, 0);
		if (error) {
			ocf_io_put(sub_io);
			cas_free_blk_data(data);
			break;
		}

		ocf_io_set_cmpl(sub_io, NULL, NULL, block_dev_complete_sub_rq);

		list_add_tail(&data->list, list);
		atomic_inc(&master_data->master_remaining);
	}

	if (error) {
		CAS_PRINT_RL(KERN_ERR "Cannot handle request (ERROR %d)\n", error);

		/* Go over list and free all */
		while (!list_empty(list)) {
			data = list_first_entry(list, struct blk_data, list);
			list_del(&data->list);

			sub_io = data->io;
			ocf_io_put(sub_io);
			cas_free_blk_data(data);
		}
	}

	return error;
}

static void _blockdev_set_request_data(struct blk_data *data, struct request *rq)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 14, 0)
	struct req_iterator iter;
	struct bio_vec *bvec;
	uint32_t i = 0;

	rq_for_each_segment(bvec, rq, iter) {
		BUG_ON(i >= data->size);
		data->vec[i] = *bvec;
		i++;
	}
#else
	struct req_iterator iter;
	struct bio_vec bvec;
	uint32_t i = 0;

	rq_for_each_segment(bvec, rq, iter) {
		BUG_ON(i >= data->size);
		data->vec[i] = bvec;
		i++;
	}
#endif
}

/**
 * @brief push flush request upon execution queue for given core device
 */
static int _blkdev_handle_flush_request(struct request *rq, ocf_core_t core)
{
	struct ocf_io *io;
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			0, 0, OCF_WRITE, 0, CAS_WRITE_FLUSH);
	if (!io)
		return -ENOMEM;

	ocf_io_set_cmpl(io, rq, NULL, block_dev_complete_flush);

	ocf_core_submit_flush(io);

	return 0;
}

#ifdef RQ_CHECK_CONTINOUS
static inline bool _bvec_is_mergeable(struct bio_vec *bv1, struct bio_vec *bv2)
{
	if (bv1 == NULL)
		return true;

	if (BIOVEC_PHYS_MERGEABLE(bv1, bv2))
		return true;

	return !bv2->bv_offset && !((bv1->bv_offset + bv1->bv_len) % PAGE_SIZE);
}
#endif

static uint32_t _blkdev_scan_request(ocf_cache_t cache, struct request *rq,
		struct ocf_io *io, bool *single_io)
{
	uint32_t size = 0;
	struct req_iterator iter;
	struct bio *bio_prev = NULL;
	uint32_t io_class;

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 14, 0)
	struct bio_vec bvec;
#ifdef RQ_CHECK_CONTINOUS
	struct bio_vec bvec_prev = { NULL, };
#endif
#else
	struct bio_vec *bvec;
#ifdef RQ_CHECK_CONTINOUS
	struct bio_vec *bvec_prev = NULL;
#endif
#endif

	*single_io = true;

	/* Scan BIOs in the request to:
	 * 1. Count the segments number
	 * 2. Check if requests contains many IO classes
	 * 3. Check if request is continuous (when process kernel stack is 8KB)
	 */
	rq_for_each_segment(bvec, rq, iter) {
		/* Increase BIO data vector counter */
		size++;

		if (*single_io == false) {
			/* Already detected complex request */
			continue;
		}

#ifdef RQ_CHECK_CONTINOUS
		/*
		 * If request is not continous submit each bio as separate
		 * request, and prevent nvme driver from splitting requests.
		 * For large requests, nvme splitting causes stack overrun.
		 */
		if (!_bvec_is_mergeable(CAS_SEGMENT_BVEC(bvec_prev),
				CAS_SEGMENT_BVEC(bvec))) {
			*single_io = false;
			continue;
		}
		bvec_prev = bvec;
#endif

		if (bio_prev == iter.bio)
			continue;

		bio_prev = iter.bio;

		/* Get class ID for given BIO */
		io_class = cas_cls_classify(cache, iter.bio);

		if (io->io_class != io_class) {
			/*
			 * Request contains BIO with different IO classes and
			 * need to handle BIO separately
			 */
			*single_io = false;
		}
	}

	return size;
}

static int __block_dev_queue_rq(struct request *rq, ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct ocf_io *io;
	struct blk_data *data;
	int master_flags = 0;
	bool single_io;
	uint32_t size;
	int ret;

	if (_blockdev_is_request_barier(rq) || !_blockdev_can_handle_rq(rq)) {
		CAS_PRINT_RL(KERN_WARNING
			"special bio was sent,not supported!\n");
		return -ENOTSUPP;
	}

	if ((rq->cmd_flags & REQ_FUA) && CAS_RQ_IS_FLUSH(rq)) {
		/* FLUSH and FUA */
		master_flags = CAS_WRITE_FLUSH_FUA;
	} else if (rq->cmd_flags & REQ_FUA) {
		/* FUA */
		master_flags = CAS_WRITE_FUA;
	} else if (CAS_RQ_IS_FLUSH(rq)) {
		/* FLUSH */
		return _blkdev_handle_flush_request(rq, core);
	}

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			BLK_RQ_POS(rq) << SECTOR_SHIFT, BLK_RQ_BYTES(rq),
			(rq_data_dir(rq) == CAS_RQ_DATA_DIR_WR) ?
					OCF_WRITE : OCF_READ,
			cas_cls_classify(cache, rq->bio), master_flags);
	if (!io) {
		CAS_PRINT_RL(KERN_CRIT "Out of memory. Ending IO processing.\n");
		return -ENOMEM;
	}


	size = _blkdev_scan_request(cache, rq, io, &single_io);

	if (unlikely(size == 0)) {
		CAS_PRINT_RL(KERN_ERR "Empty IO request\n");
		ocf_io_put(io);
		return -EINVAL;
	}

	if (single_io) {
		data = cas_alloc_blk_data(size, GFP_NOIO);
		if (data == NULL) {
			CAS_PRINT_RL(KERN_CRIT
				"Out of memory. Ending IO processing.\n");
			ocf_io_put(io);
			return -ENOMEM;
		}

		_blockdev_set_request_data(data, rq);

		data->master_io_req = rq;

		ret = ocf_io_set_data(io, data, 0);
		if (ret) {
			ocf_io_put(io);
			cas_free_blk_data(data);
			return -EINVAL;
		}

		ocf_io_set_cmpl(io, NULL, NULL, block_dev_complete_rq);

		ocf_core_submit_io(io);
	} else {
		struct list_head list = LIST_HEAD_INIT(list);

		data = cas_alloc_blk_data(0, GFP_NOIO);
		if (data == NULL) {
			printk(KERN_CRIT
				"Out of memory. Ending IO processing.\n");
			ocf_io_put(io);
			return -ENOMEM;
		}
		data->master_io_req = rq;

		if (ocf_io_set_data(io, data, 0)) {
			ocf_io_put(io);
			cas_free_blk_data(data);
			return -EINVAL;
		}

		/* Allocate setup and setup */
		ret = _blockdev_alloc_many_requests(core, &list, rq, io);
		if (ret < 0) {
			printk(KERN_CRIT
				"Out of memory. Ending IO processing.\n");
			cas_free_blk_data(data);
			ocf_io_put(io);
			return -ENOMEM;
		}

		BUG_ON(list_empty(&list));

		/* Go over list and push request to the engine */
		while (!list_empty(&list)) {
			struct ocf_io *sub_io;

			data = list_first_entry(&list, struct blk_data, list);
			list_del(&data->list);

			sub_io = data->io;

			ocf_core_submit_io(sub_io);
		}
	}

	return ret;
}

static CAS_BLK_STATUS_T _block_dev_queue_request(struct casdsk_disk *dsk, struct request *rq, void *private)
{
	ocf_core_t core = private;
	int ret = __block_dev_queue_rq(rq, core);
	if (ret)
		_blockdev_end_request_all(rq, ret);

	return CAS_ERRNO_TO_BLK_STS(ret);
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

static inline bool _blkdev_is_flush_fua_bio(struct bio *bio)
{
	if (CAS_IS_WRITE_FLUSH_FUA(CAS_BIO_OP_FLAGS(bio))) {
		/* FLUSH and FUA */
		return true;
	} else if (CAS_IS_WRITE_FUA(CAS_BIO_OP_FLAGS(bio))) {
		/* FUA */
		return true;
	} else if (CAS_IS_WRITE_FLUSH(CAS_BIO_OP_FLAGS(bio))) {
		/* FLUSH */
		return true;

	}

	return false;
}

void _blockdev_set_exported_object_flush_fua(ocf_core_t core)
{
#ifdef CAS_FLUSH_SUPPORTED
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
#endif
}

static int _blockdev_calc_discard_alignment(ocf_cache_t cache,
		struct block_device *core_bd)
{
	unsigned int granularity, offset;
	sector_t start;

	if (core_bd == core_bd->bd_contains)
		return 0;

	start = core_bd->bd_part->start_sect;
	granularity = ocf_cache_get_line_size(cache) >> SECTOR_SHIFT;

	offset = sector_div(start, granularity);
	offset = (granularity - offset) % granularity;

	return offset << SECTOR_SHIFT;
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
		blk_queue_max_discard_sectors(exp_q, core_sectors);
		exp_q->limits.discard_granularity =
			ocf_cache_get_line_size(cache);
		exp_q->limits.discard_alignment =
			_blockdev_calc_discard_alignment(cache, core_bd);
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

	blk_queue_stack_limits(exp_q, core_q);

	/* We don't want to receive splitted requests*/
	CAS_SET_QUEUE_CHUNK_SECTORS(exp_q, 0);

	_blockdev_set_exported_object_flush_fua(core);

	_blockdev_set_discard_properties(cache, exp_q, cache_bd, core_bd,
			sectors);

	return 0;
}

static void _blockdev_pending_req_inc(struct casdsk_disk *dsk, void *private)
{
	ocf_core_t core;
	ocf_volume_t obj;
	struct bd_object *bvol;

	BUG_ON(!private);
	core = private;
	obj = ocf_core_get_volume(core);
	bvol = bd_object(obj);
	BUG_ON(!bvol);

	atomic64_inc(&bvol->pending_rqs);
}

static void _blockdev_pending_req_dec(struct casdsk_disk *dsk, void *private)
{
	ocf_core_t core;
	ocf_volume_t obj;
	struct bd_object *bvol;

	BUG_ON(!private);
	core = private;
	obj = ocf_core_get_volume(core);
	bvol = bd_object(obj);
	BUG_ON(!bvol);

	atomic64_dec(&bvol->pending_rqs);
}

static void _blockdev_make_request_discard(struct casdsk_disk *dsk,
		struct request_queue *q, struct bio *bio, void *private)
{
	ocf_core_t core = private;
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

	ocf_io_set_cmpl(io, bio, NULL, block_dev_complete_bio_discard);

	ocf_core_submit_discard(io);
}

static int _blockdev_make_request_fast(struct casdsk_disk *dsk,
		struct request_queue *q, struct bio *bio, void *private)
{
	ocf_core_t core;
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	struct ocf_io *io;
	struct blk_data *data;
	int ret;

	BUG_ON(!private);
	core = private;
	cache = ocf_core_get_cache(core);
	cache_priv = ocf_cache_get_priv(cache);

	if (in_interrupt())
		return CASDSK_BIO_NOT_HANDLED;

	if (_blkdev_can_hndl_bio(bio))
		return CASDSK_BIO_HANDLED;

	if (_blkdev_is_flush_fua_bio(bio))
		return CASDSK_BIO_NOT_HANDLED;

	if (CAS_IS_DISCARD(bio)) {
		_blockdev_make_request_discard(dsk, q, bio, private);
		return CASDSK_BIO_HANDLED;
	}

	if (unlikely(CAS_BIO_BISIZE(bio) == 0)) {
		CAS_PRINT_RL(KERN_ERR
			"Not able to handle empty BIO, flags = "
			CAS_BIO_OP_FLAGS_FORMAT "\n",  CAS_BIO_OP_FLAGS(bio));
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-EINVAL));
		return CASDSK_BIO_HANDLED;
	}

	data = cas_alloc_blk_data(bio_segments(bio), GFP_NOIO);
	if (!data) {
		CAS_PRINT_RL(KERN_CRIT "BIO data vector allocation error\n");
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return CASDSK_BIO_HANDLED;
	}

	_blockdev_set_bio_data(data, bio);

	data->master_io_req = bio;
	data->start_time = jiffies;

	io = ocf_core_new_io(core, cache_priv->io_queues[smp_processor_id()],
			CAS_BIO_BISECTOR(bio) << SECTOR_SHIFT,
			CAS_BIO_BISIZE(bio), (bio_data_dir(bio) == READ) ?
					OCF_READ : OCF_WRITE,
			cas_cls_classify(cache, bio), 0);

	if (!io) {
		printk(KERN_CRIT "Out of memory. Ending IO processing.\n");
		cas_free_blk_data(data);
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-ENOMEM));
		return CASDSK_BIO_HANDLED;
	}

	ret = ocf_io_set_data(io, data, 0);
	if (ret < 0) {
		ocf_io_put(io);
		cas_free_blk_data(data);
		CAS_BIO_ENDIO(bio, CAS_BIO_BISIZE(bio), CAS_ERRNO_TO_BLK_STS(-EINVAL));
		return CASDSK_BIO_HANDLED;
	}

	ocf_io_set_cmpl(io, NULL, NULL, block_dev_complete_bio_fast);
	ocf_io_set_start(io, block_dev_start_bio_fast);

	ret = ocf_core_submit_io_fast(io);
	if (ret < 0)
		goto err;

	return CASDSK_BIO_HANDLED;

err:
	/*
	 * - Not able to processed fast path for this BIO,
	 * - Cleanup current request
	 * - Put it to the IO scheduler
	 */
	ocf_io_put(io);
	cas_free_blk_data(data);

	return CASDSK_BIO_NOT_HANDLED;
}

static struct casdsk_exp_obj_ops _blockdev_exp_obj_ops = {
	.set_geometry = _blockdev_set_geometry,
	.make_request_fn = _blockdev_make_request_fast,
	.queue_rq_fn = _block_dev_queue_request,
	.pending_rq_inc = _blockdev_pending_req_inc,
	.pending_rq_dec = _blockdev_pending_req_dec,
};

/**
 * @brief this routine actually adds /dev/casM-N inode
 */
int block_dev_activate_exported_object(ocf_core_t core)
{
	int ret;
	ocf_volume_t obj = ocf_core_get_volume(core);
	struct bd_object *bvol = bd_object(obj);

	if (!cas_upgrade_is_in_upgrade()) {
		ret = casdisk_functions.casdsk_exp_obj_activate(bvol->dsk);
		if (-EEXIST == ret)
			return KCAS_ERR_FILE_EXISTS;
	} else {
		ret = casdisk_functions.casdsk_disk_attach(bvol->dsk, THIS_MODULE,
				&_blockdev_exp_obj_ops);
	}
	return ret;
}

static int _block_dev_activate_exported_object(ocf_core_t core, void *cntx)
{
	return block_dev_activate_exported_object(core);
}

int block_dev_activate_all_exported_objects(ocf_cache_t cache)
{
	return ocf_core_visit(cache, _block_dev_activate_exported_object, NULL,
			true);
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
	if (dsk != bvol->dsk)
		return -KCAS_ERR_SYSTEM;

	if (cas_upgrade_is_in_upgrade()) {
		bvol->expobj_valid = true;
		return 0;
	}

	result = casdisk_functions.casdsk_exp_obj_create(dsk, dev_name,
			THIS_MODULE, &_blockdev_exp_obj_ops);
	if (!result)
		bvol->expobj_valid = true;

	return result;
}

static int _block_dev_create_exported_object_visitor(ocf_core_t core, void *cntx)
{
	return block_dev_create_exported_object(core);
}

int block_dev_create_all_exported_objects(ocf_cache_t cache)
{
	return ocf_core_visit(cache, _block_dev_create_exported_object_visitor, NULL,
			true);
}

int block_dev_destroy_exported_object(ocf_core_t core)
{
	int result = 0;
	ocf_volume_t obj = ocf_core_get_volume(core);
	struct bd_object *bvol = bd_object(obj);

	if (!bvol->expobj_valid)
		return 0;

	result = casdisk_functions.casdsk_exp_obj_lock(bvol->dsk);
	if (result) {
		if (EBUSY == abs(result))
			result = -KCAS_ERR_DEV_PENDING;
		return result;
	}

	result = casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
	casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);

	if (!result)
		bvol->expobj_valid = false;

	return result;
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

	if (bvol->expobj_valid) {
		BUG_ON(!bvol->expobj_locked);

		printk(KERN_INFO "Stopping device %s\n",
			casdisk_functions.casdsk_exp_obj_get_gendisk(bvol->dsk)->disk_name);

		casdisk_functions.casdsk_exp_obj_destroy(bvol->dsk);
		bvol->expobj_valid = false;
	}

	if (bvol->expobj_locked) {
		casdisk_functions.casdsk_exp_obj_unlock(bvol->dsk);
		bvol->expobj_locked = false;
	}

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

	block_dev_free_all_exported_objects(cache);
	return 0;
}

static int _block_dev_free_exported_object(ocf_core_t core, void *cntx)
{
	struct bd_object *bvol = bd_object(
			ocf_core_get_volume(core));

	casdisk_functions.casdsk_exp_obj_free(bvol->dsk);
	return 0;
}

int block_dev_free_all_exported_objects(ocf_cache_t cache)
{
	return ocf_core_visit(cache, _block_dev_free_exported_object, NULL,
			true);
}
