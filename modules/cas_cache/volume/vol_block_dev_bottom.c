/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
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

static int block_dev_open_object(ocf_volume_t vol, void *volume_params)
{
	struct bd_object *bdobj = bd_object(vol);
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(vol);
	struct cas_disk *dsk;

	if (bdobj->opened_by_bdev) {
		/* Bdev has been set manually, so there is nothing to do. */
		return 0;
	}

	dsk = cas_disk_open(uuid->data);
	if (IS_ERR_OR_NULL(dsk)) {
		int error = PTR_ERR(dsk) ?: -EINVAL;

		if (error == -EBUSY)
			error = -OCF_ERR_NOT_OPEN_EXC;

		return error;
	}

	bdobj->dsk = dsk;
	bdobj->btm_bd = cas_disk_get_blkdev(dsk);

	return 0;
}

static void block_dev_close_object(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);

	if (bdobj->opened_by_bdev)
		return;

	cas_disk_close(bdobj->dsk);
}

static unsigned int block_dev_get_max_io_size(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);
	struct block_device *bd = bdobj->btm_bd;

	return queue_max_sectors(bd->bd_disk->queue) << SECTOR_SHIFT;
}

static uint64_t block_dev_get_byte_length(ocf_volume_t vol)
{
	struct bd_object *bdobj = bd_object(vol);
	struct block_device *bd = bdobj->btm_bd;
	uint64_t sector_length;

	sector_length = (cas_bdev_whole(bd) == bd) ?
			get_capacity(bd->bd_disk) :
			cas_bdev_nr_sectors(bd);

	return sector_length << SECTOR_SHIFT;
}

/*
 *
 */
static inline struct bio *cas_bd_io_alloc_bio(struct block_device *bdev, 
					      struct bio_vec_iter *iter)
{
	struct bio *bio
		= cas_bio_alloc(bdev, GFP_NOIO, cas_io_iter_size_left(iter));

	if (bio)
		return bio;

	if (cas_io_iter_size_left(iter) < MAX_LINES_PER_IO) {
		/* BIO vector was small, so it was memory
		 * common problem - NO RAM!!!
		 */
		return NULL;
	}

	/* Retry with smaller */
	return cas_bio_alloc(bdev, GFP_NOIO, MAX_LINES_PER_IO);
}

/*
 * Returns only flags that are relevant to request's direction.
 */
static inline uint64_t filter_req_flags(int dir, uint64_t flags)
{
	/* Remove REQ_RAHEAD flag from write request to cache which are a
	   result of a missed read-head request. This flag caused the nvme
	   driver to send write command with access frequency value that is
	   reserved */
	if (dir == WRITE)
		flags &= ~REQ_RAHEAD;

	return flags;
}

/*
 *
 */
CAS_DECLARE_BLOCK_CALLBACK(cas_bd_forward_end, struct bio *bio,
		unsigned int bytes_done, int error)
{
	ocf_forward_token_t token;
	int err;

	CAS_BLOCK_CALLBACK_INIT(bio);
	token = (ocf_forward_token_t)bio->bi_private;
	err = CAS_BLOCK_CALLBACK_ERROR(bio, error);

	CAS_DEBUG_TRACE();

	if (err == -EOPNOTSUPP && (CAS_BIO_OP_FLAGS(bio) & CAS_BIO_DISCARD))
		err = 0;

	ocf_forward_end(token, err);

	bio_put(bio);
	CAS_BLOCK_CALLBACK_RETURN();
}


static void block_dev_forward_io(ocf_volume_t volume,
		ocf_forward_token_t token, int dir, uint64_t addr,
		uint64_t bytes, uint64_t offset)
{
	struct ocf_io *io = ocf_forward_get_io(token);
	struct bd_object *bdobj = bd_object(volume);
	struct blk_data *data = ocf_io_get_data(io);
	int bio_dir = (dir == OCF_READ) ? READ : WRITE;
	struct bio_vec_iter iter;
	struct blk_plug plug;
	int error = 0;

	CAS_DEBUG_PARAM("Address = %llu, bytes = %u\n", addr, bytes);

	cas_io_iter_init(&iter, data->vec, data->size);
	if (offset != cas_io_iter_move(&iter, offset)) {
		ocf_forward_end(token, -OCF_ERR_INVAL);
		return;
	}

	blk_start_plug(&plug);
	while (cas_io_iter_is_next(&iter) && bytes) {
		/* Still IO vectors to be sent */

		/* Allocate BIO */
		struct bio *bio = cas_bd_io_alloc_bio(bdobj->btm_bd, &iter);

		if (!bio) {
			error = -ENOMEM;
			break;
		}

		/* Setup BIO */
		CAS_BIO_SET_DEV(bio, bdobj->btm_bd);
		CAS_BIO_BISECTOR(bio) = addr / SECTOR_SIZE;
		bio->bi_next = NULL;
		bio->bi_private = (void *)token;
		CAS_BIO_OP_FLAGS(bio) |= filter_req_flags(bio_dir, io->flags);
		bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_forward_end);

		/* Add pages */
		while (cas_io_iter_is_next(&iter) && bytes) {
			struct page *page = cas_io_iter_current_page(&iter);
			uint32_t offset = cas_io_iter_current_offset(&iter);
			uint32_t length = cas_io_iter_current_length(&iter);
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
			if (added != cas_io_iter_move(&iter, added)) {
				error = -ENOBUFS;
				break;
			}
		}

		if (error == 0) {
			/* Increase IO reference for sending this IO */

			ocf_forward_get(token);
			/* Send BIO */
			CAS_DEBUG_MSG("Submit IO");
			cas_submit_bio(bio_dir, bio);
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

	if (bytes && error == 0) {
		/* Not all bytes sent, mark error */
		error = -ENOBUFS;
	}

	/* Prevent races of completing IO when
	 * there are still child IOs not being send.
	 */
	ocf_forward_end(token, error);
}

static void block_dev_forward_flush(ocf_volume_t volume,
		ocf_forward_token_t token)
{
	struct ocf_io *io = ocf_forward_get_io(token);
	struct bd_object *bdobj = bd_object(volume);
	struct request_queue *q = bdev_get_queue(bdobj->btm_bd);
	int bio_dir = (io->dir == OCF_READ) ? READ : WRITE;
	struct bio *bio;

	if (!q) {
		/* No queue, error */
		ocf_forward_end(token, -OCF_ERR_INVAL);
		return;
	}

	if (!CAS_CHECK_QUEUE_FLUSH(q)) {
		/* This block device does not support flush, call back */
		ocf_forward_end(token, 0);
		return;
	}

	bio = cas_bio_alloc(bdobj->btm_bd, GFP_NOIO, 0);
	if (!bio) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate memory for BIO\n");
		ocf_forward_end(token, -OCF_ERR_NO_MEM);
		return;
	}

	CAS_BIO_SET_DEV(bio, bdobj->btm_bd);
	bio->bi_private = (void *)token;
	bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_forward_end);

	cas_submit_bio(CAS_SET_FLUSH(bio_dir), bio);

}

static void block_dev_forward_discard(ocf_volume_t volume,
		ocf_forward_token_t token, uint64_t addr, uint64_t bytes)
{
	struct bd_object *bdobj = bd_object(volume);
	struct request_queue *q = bdev_get_queue(bdobj->btm_bd);
	struct bio *bio;
	int error = 0;

	unsigned int max_discard_sectors, granularity, bio_sects;
	int alignment;
	sector_t sects, start, end, tmp;

	if (!q) {
		/* No queue, error */
		ocf_forward_end(token, -OCF_ERR_INVAL);
		return;
	}

	if (!cas_has_discard_support(bdobj->btm_bd)) {
		/* Discard is not supported by bottom device, send completion
		 * to caller
		 */
		ocf_forward_end(token, 0);
		return;
	}

	granularity = max(q->limits.discard_granularity >> SECTOR_SHIFT, 1U);
	alignment = (bdev_discard_alignment(bdobj->btm_bd) >> SECTOR_SHIFT)
			% granularity;
	max_discard_sectors =
		min(q->limits.max_discard_sectors, UINT_MAX >> SECTOR_SHIFT);
	max_discard_sectors -= max_discard_sectors % granularity;
	if (unlikely(!max_discard_sectors)) {
		ocf_forward_end(token, -OCF_ERR_INVAL);
		return;
	}

	sects = bytes >> SECTOR_SHIFT;
	start = addr >> SECTOR_SHIFT;

	while (sects) {
		bio = cas_bio_alloc(bdobj->btm_bd, GFP_NOIO, 1);
		if (!bio) {
			CAS_PRINT_RL(CAS_KERN_ERR "Couldn't allocate memory for BIO\n");
			error = -OCF_ERR_NO_MEM;
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

		CAS_BIO_SET_DEV(bio, bdobj->btm_bd);
		CAS_BIO_BISECTOR(bio) = start;
		CAS_BIO_BISIZE(bio) = bio_sects << SECTOR_SHIFT;
		bio->bi_next = NULL;
		bio->bi_private = (void *)token;
		bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_bd_forward_end);

		ocf_forward_get(token);
		cas_submit_bio(CAS_BIO_DISCARD, bio);

		sects -= bio_sects;
		start = end;

		cond_resched();
	}

	ocf_forward_end(token, error);
}

const struct ocf_volume_properties cas_object_blk_properties = {
	.name = "Block_Device",
	.volume_priv_size = sizeof(struct bd_object),
	.caps = {
		.atomic_writes = 0, /* Atomic writes not supported */
	},
	.ops = {
		.forward_io = block_dev_forward_io,
		.forward_flush = block_dev_forward_flush,
		.forward_discard = block_dev_forward_discard,
		.open = block_dev_open_object,
		.close = block_dev_close_object,
		.get_max_io_size = block_dev_get_max_io_size,
		.get_length = block_dev_get_byte_length,
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
