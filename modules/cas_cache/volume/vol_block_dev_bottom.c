/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <linux/blkdev.h>

#include "cas_cache.h"

#define CAS_DEBUG_IO 0

#if CAS_DEBUG_IO == 1
#define CAS_DEBUG_TRACE() printk(KERN_DEBUG \
		"[IO] %s:%d\n", __func__, __LINE__)

#define CAS_DEBUG_MSG(msg) printk(KERN_DEBUG \
		"[IO] %s:%d - %s\n", __func__, __LINE__, msg)

#define CAS_DEBUG_PARAM(format, ...) printk(KERN_DEBUG \
		"[IO] %s:%d - "format"\n", __func__, __LINE__, ##__VA_ARGS__)
#else
#define CAS_DEBUG_TRACE()
#define CAS_DEBUG_MSG(msg)
#define CAS_DEBUG_PARAM(format, ...)
#endif

int block_dev_open_object(ocf_volume_t vol, void *volume_params)
{
	struct bd_object *bdobj = bd_object(vol);
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(vol);
	struct casdsk_disk *dsk;

	if (bdobj->opened_by_bdev) {
		/* Bdev has been set manually, so there is nothing to do. */
		return 0;
	}

	dsk = casdisk_functions.casdsk_disk_open(uuid->data, NULL);
	if (IS_ERR_OR_NULL(dsk)) {
		int error = PTR_ERR(dsk) ?: -EINVAL;

		if (error == -EBUSY)
			error = -OCF_ERR_NOT_OPEN_EXC;

		return error;
	}

	bdobj->dsk = dsk;
	bdobj->btm_bd = casdisk_functions.casdsk_disk_get_blkdev(dsk);

	return 0;
}

void block_dev_close_object(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);

	if (bdobj->opened_by_bdev)
		return;

	casdisk_functions.casdsk_disk_close(bdobj->dsk);
}

unsigned int block_dev_get_max_io_size(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);
	struct block_device *bd = bdobj->btm_bd;

	return queue_max_sectors(bd->bd_disk->queue) << SECTOR_SHIFT;
}

uint64_t block_dev_get_byte_length(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);
	struct block_device *bd = bdobj->btm_bd;
	uint64_t sector_length;

	sector_length = (cas_bdev_whole(bd) == bd) ?
			get_capacity(bd->bd_disk) :
			cas_bdev_nr_sectors(bd);

	return sector_length << SECTOR_SHIFT;
}

#if LINUX_VERSION_CODE <= KERNEL_VERSION(3, 3, 0)
static const char *__block_dev_get_elevator_name(struct request_queue *q)
{
	if (q->elevator->elevator_type == NULL)
		return NULL;

	if (q->elevator->elevator_type->elevator_name == NULL)
		return NULL;

	if (q->elevator->elevator_type->elevator_name[0] == 0)
		return NULL;

	return q->elevator->elevator_type->elevator_name;
}
#else
static const char *__block_dev_get_elevator_name(struct request_queue *q)
{
	if (q->elevator->type == NULL)
		return NULL;

	if (q->elevator->type->elevator_name == NULL)
		return NULL;

	if (q->elevator->type->elevator_name[0] == 0)
		return NULL;

	return q->elevator->type->elevator_name;
}
#endif

/*
 *
 */
const char *block_dev_get_elevator_name(struct request_queue *q)
{
	if (!q)
		return NULL;

	if (q->elevator == NULL)
		return NULL;

	return __block_dev_get_elevator_name(q);
}

/*
 *
 */
static inline struct bio *cas_bd_io_alloc_bio(struct blkio *bdio)
{
	struct bio *bio
		= bio_alloc(GFP_NOIO, cas_io_iter_size_left(&bdio->iter));

	if (bio)
		return bio;

	if (cas_io_iter_size_left(&bdio->iter) < MAX_LINES_PER_IO) {
		/* BIO vector was small, so it was memory
		 * common problem - NO RAM!!!
		 */
		return NULL;
	}

	/* Retry with smaller */
	return bio_alloc(GFP_NOIO, MAX_LINES_PER_IO);
}

/*
 *
 */
static void cas_bd_io_end(struct ocf_io *io, int error)
{
	struct blkio *bdio = cas_io_to_blkio(io);

	if (error)
		bdio->error |= error;

	if (atomic_dec_return(&bdio->rq_remaning))
		return;

	CAS_DEBUG_MSG("Completion");

	/* Send completion to caller */
	io->end(io, bdio->error);
}

/*
 *
 */
CAS_DECLARE_BLOCK_CALLBACK(cas_bd_io_end, struct bio *bio,
		unsigned int bytes_done, int error)
{
	struct ocf_io *io;
	struct blkio *bdio;
	struct bd_object *bdobj;
	int err;

	BUG_ON(!bio);
	BUG_ON(!bio->bi_private);
	CAS_BLOCK_CALLBACK_INIT(bio);
	io = bio->bi_private;
	bdobj = bd_object(ocf_io_get_volume(io));
	BUG_ON(!bdobj);
	err = CAS_BLOCK_CALLBACK_ERROR(bio, error);
	bdio = cas_io_to_blkio(io);
	BUG_ON(!bdio);

	CAS_DEBUG_TRACE();

	if (err == -EOPNOTSUPP && (CAS_BIO_OP_FLAGS(bio) & CAS_BIO_DISCARD))
		err = 0;

	cas_bd_io_end(io, err);

	bio_put(bio);
	CAS_BLOCK_CALLBACK_RETURN();
}

static void block_dev_submit_flush(struct ocf_io *io)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct block_device *bdev = bdobj->btm_bd;
	struct request_queue *q = bdev_get_queue(bdev);
	struct bio *bio = NULL;

	/* Prevent races of completing IO */
	atomic_set(&blkio->rq_remaning, 1);

	if (q == NULL) {
		/* No queue, error */
		blkio->error = -EINVAL;
		goto out;
	}

	if (!CAS_CHECK_QUEUE_FLUSH(q)) {
		/* This block device does not support flush, call back */
		goto out;
	}

	bio = bio_alloc(GFP_NOIO, 0);
	if (bio == NULL) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate memory for BIO\n");
		blkio->error = -ENOMEM;
		goto out;
	}

	blkio->dir = io->dir;

	bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_io_end);
	CAS_BIO_SET_DEV(bio, bdev);
	bio->bi_private = io;

	atomic_inc(&blkio->rq_remaning);
	cas_submit_bio(CAS_SET_FLUSH(io->dir), bio);

out:
	cas_bd_io_end(io, blkio->error);
}

void block_dev_submit_discard(struct ocf_io *io)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct block_device *bd = bdobj->btm_bd;
	struct request_queue *q = bdev_get_queue(bd);
	struct bio *bio = NULL;

	unsigned int max_discard_sectors, granularity, bio_sects;
	int alignment;
	sector_t sects, start, end, tmp;

	/* Prevent races of completing IO */
	atomic_set(&blkio->rq_remaning, 1);

	if (!q) {
		/* No queue, error */
		blkio->error = -ENXIO;
		goto out;
	}

	if (!blk_queue_discard(q)) {
		/* Discard is not supported by bottom device, send completion
		 * to caller
		 */
		goto out;
	}

	granularity = max(q->limits.discard_granularity >> SECTOR_SHIFT, 1U);
	alignment = (bdev_discard_alignment(bd) >> SECTOR_SHIFT) % granularity;
	max_discard_sectors =
		min(q->limits.max_discard_sectors, UINT_MAX >> SECTOR_SHIFT);
	max_discard_sectors -= max_discard_sectors % granularity;
	if (unlikely(!max_discard_sectors))
		goto out;

	sects = io->bytes >> SECTOR_SHIFT;
	start = io->addr >> SECTOR_SHIFT;

	while (sects) {
		bio = bio_alloc(GFP_NOIO, 1);
		if (!bio) {
			CAS_PRINT_RL(CAS_KERN_ERR "Couldn't allocate memory for BIO\n");
			blkio->error = -ENOMEM;
			break;
		}

		bio_sects = min_t(sector_t, sects, max_discard_sectors);
		end = start + bio_sects;
		tmp = end;
		if (bio_sects < sects &&
		    sector_div(tmp, granularity) != alignment) {
			end = end - alignment;
			sector_div(end, granularity);
			end = end * granularity + alignment;
			bio_sects = end - start;
		}

		CAS_BIO_SET_DEV(bio, bd);
		CAS_BIO_BISECTOR(bio) = start;
		CAS_BIO_BISIZE(bio) = bio_sects << SECTOR_SHIFT;
		bio->bi_next = NULL;
		bio->bi_private = io;
		bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_io_end);

		atomic_inc(&blkio->rq_remaning);
		cas_submit_bio(CAS_BIO_DISCARD, bio);

		sects -= bio_sects;
		start = end;

		cond_resched();
	}

out:
	cas_bd_io_end(io, blkio->error);
}

static inline bool cas_bd_io_prepare(int *dir, struct ocf_io *io)
{
	struct blkio *bdio = cas_io_to_blkio(io);

	/* Setup DIR */
	bdio->dir = *dir;

	/* Convert CAS direction into kernel values */
	switch (bdio->dir) {
	case OCF_READ:
		*dir = READ;
		break;

	case OCF_WRITE:
		*dir = WRITE;
		break;

	default:
		bdio->error = -EINVAL;
		break;
	}

	if (!io->bytes) {
		/* Don not accept empty request */
		CAS_PRINT_RL(KERN_ERR "Invalid zero size IO\n");
		bdio->error = -EINVAL;
	}

	if (bdio->error)
		return false;

	return true;
}

/*
 *
 */
static void block_dev_submit_io(struct ocf_io *io)
{
	struct blkio *bdio = cas_io_to_blkio(io);
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct bio_vec_iter *iter = &bdio->iter;
	uint64_t addr = io->addr;
	uint32_t bytes = io->bytes;
	int dir = io->dir;
	struct blk_plug plug;

	if (CAS_IS_SET_FLUSH(io->flags)) {
		CAS_DEBUG_MSG("Flush request");
		/* It is flush requests handle it */
		block_dev_submit_flush(io);
		return;
	}

	CAS_DEBUG_PARAM("Address = %llu, bytes = %u\n", bdio->addr,
			bdio->bytes);

	/* Prevent races of completing IO */
	atomic_set(&bdio->rq_remaning, 1);

	if (!cas_bd_io_prepare(&dir, io)) {
		CAS_DEBUG_MSG("Invalid request");
		cas_bd_io_end(io, -EINVAL);
		return;
	}

	blk_start_plug(&plug);

	while (cas_io_iter_is_next(iter) && bytes) {
		/* Still IO vectors to be sent */

		/* Allocate BIO */
		struct bio *bio = cas_bd_io_alloc_bio(bdio);

		if (!bio) {
			bdio->error = -ENOMEM;
			break;
		}

		/* Setup BIO */
		CAS_BIO_SET_DEV(bio, bdobj->btm_bd);
		CAS_BIO_BISECTOR(bio) = addr / SECTOR_SIZE;
		bio->bi_next = NULL;
		bio->bi_private = io;
		CAS_BIO_OP_FLAGS(bio) |= io->flags;
		bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_io_end);

		/* Add pages */
		while (cas_io_iter_is_next(iter) && bytes) {
			struct page *page = cas_io_iter_current_page(iter);
			uint32_t offset = cas_io_iter_current_offset(iter);
			uint32_t length = cas_io_iter_current_length(iter);
			int added;

			if (length > bytes)
				length = bytes;

			added = bio_add_page(bio, page, length, offset);
			BUG_ON(added < 0);

			if (added == 0) {
				/* No more space in BIO, stop adding pages */
				break;
			}

			/* Update address, bytes sent */
			bytes -= added;
			addr += added;

			/* Update BIO vector iterator */
			if (added != cas_io_iter_move(iter, added)) {
				bdio->error = -ENOBUFS;
				break;
			}
		}

		if (bdio->error == 0) {
			/* Increase IO reference for sending this IO */
			atomic_inc(&bdio->rq_remaning);

			/* Send BIO */
			CAS_DEBUG_MSG("Submit IO");
			cas_submit_bio(dir, bio);
			bio = NULL;
		} else {
			if (bio) {
				bio_put(bio);
				bio = NULL;
			}

			/* ERROR, stop processed */
			break;
		}
	}

	blk_finish_plug(&plug);

	if (bytes && bdio->error == 0) {
		/* Not all bytes sent, mark error */
		bdio->error = -ENOBUFS;
	}

	/* Prevent races of completing IO when
	 * there are still child IOs not being send.
	 */
	cas_bd_io_end(io, 0);
}

const struct ocf_volume_properties cas_object_blk_properties = {
	.name = "Block_Device",
	.io_priv_size = sizeof(struct blkio),
	.volume_priv_size = sizeof(struct bd_object),
	.caps = {
		.atomic_writes = 0, /* Atomic writes not supported */
	},
	.ops = {
		.submit_io = block_dev_submit_io,
		.submit_flush = block_dev_submit_flush,
		.submit_metadata = NULL,
		.submit_discard = block_dev_submit_discard,
		.open = block_dev_open_object,
		.close = block_dev_close_object,
		.get_max_io_size = block_dev_get_max_io_size,
		.get_length = block_dev_get_byte_length,
	},
	.io_ops = {
		.set_data = cas_blk_io_set_data,
		.get_data = cas_blk_io_get_data,
	},
	.deinit = NULL,
};

int block_dev_init(void)
{
	int ret;

	ret = ocf_ctx_register_volume_type(cas_ctx, BLOCK_DEVICE_VOLUME,
			&cas_object_blk_properties);
	if (ret < 0)
		return ret;

	return 0;
}

int block_dev_try_get_io_class(struct bio *bio, int *io_class)
{
	struct ocf_io *io;

	if (bio->bi_end_io != CAS_REFER_BLOCK_CALLBACK(cas_bd_io_end))
		return -1;

	io = bio->bi_private;
	*io_class = io->io_class;
	return 0;
}
