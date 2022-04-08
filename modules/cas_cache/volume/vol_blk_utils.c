/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "vol_blk_utils.h"

static void cas_io_iter_advanced(struct bio_vec_iter *iter, uint32_t bytes)
{
	BUG_ON(bytes > iter->len);

	iter->len -= bytes;
	iter->offset += bytes;

	if (iter->len) {
		/* Still in this item, bytes to be processed */
		return;
	}

	/* Move to next item in data vector */
	iter->idx++;
	if (iter->idx < iter->vec_size) {
		iter->ivec = &iter->vec[iter->idx];
		iter->len = iter->ivec->bv_len;
		iter->offset = iter->ivec->bv_offset;
	} else {
		iter->ivec = NULL;
		iter->len = 0;
		iter->offset = 0;
	}
}

uint32_t cas_io_iter_cpy(struct bio_vec_iter *dst, struct bio_vec_iter *src,
		uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst, *asrc;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	if (src->idx >= src->vec_size)
		return 0;

	BUG_ON(src->offset + src->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(dst->len, src->len);
		to_copy = min(to_copy, bytes);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;
		asrc = page_address(src->ivec->bv_page) + src->offset;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(dst, to_copy);
		cas_io_iter_advanced(src, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_cpy_from_data(struct bio_vec_iter *dst,
		const void *src, uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst;
	const void *asrc;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(dst->len, bytes);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;
		asrc = src + written;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(dst, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_cpy_to_data(void *dst, struct bio_vec_iter *src,
		uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst, *asrc;

	BUG_ON(dst == NULL);

	if (src->idx >= src->vec_size)
		return 0;

	BUG_ON(src->offset + src->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(bytes, src->len);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = dst + written;
		asrc = page_address(src->ivec->bv_page) + src->offset;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(src, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_move(struct bio_vec_iter *iter, uint32_t bytes)
{
	uint32_t to_move, moved = 0;

	if (iter->idx >= iter->vec_size)
		return 0;

	BUG_ON(iter->offset + iter->len > PAGE_SIZE);

	while (bytes) {
		to_move = min(iter->len, bytes);
		if (to_move == 0) {
			/* No more bytes for coping */
			break;
		}

		bytes -= to_move;
		moved += to_move;

		cas_io_iter_advanced(iter, to_move);
	}

	return moved;
}

uint32_t cas_io_iter_zero(struct bio_vec_iter *dst, uint32_t bytes)
{
	uint32_t to_fill, zeroed = 0;
	void *adst;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	while (bytes) {
		to_fill = min(dst->len, (typeof(dst->len))PAGE_SIZE);
		if (to_fill == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;

		memset(adst, 0, to_fill);

		bytes -= to_fill;
		zeroed += to_fill;

		cas_io_iter_advanced(dst, to_fill);
	}

	return zeroed;
}

/*
 *
 */
int cas_blk_io_set_data(struct ocf_io *io,
		ctx_data_t *ctx_data, uint32_t offset)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	struct blk_data *data = ctx_data;

	/* Set BIO vector (IO data) and initialize iterator */
	blkio->data = data;
	if (blkio->data) {
		cas_io_iter_init(&blkio->iter, blkio->data->vec,
				blkio->data->size);

		/* Move into specified offset in BIO vector iterator */
		if (offset != cas_io_iter_move(&blkio->iter, offset)) {
			/* TODO Log message */
			blkio->error = -ENOBUFS;
			return -ENOBUFS;
		}
	}

	return 0;
}

/*
 *
 */
ctx_data_t *cas_blk_io_get_data(struct ocf_io *io)
{
	struct blkio *blkio = cas_io_to_blkio(io);

	return blkio->data;
}

int cas_blk_open_volume_by_bdev(ocf_volume_t *vol, struct block_device *bdev)
{
	struct bd_object *bdobj;
	int ret;

	ret = ocf_ctx_volume_create(cas_ctx, vol, NULL, BLOCK_DEVICE_VOLUME);
	if (ret)
		goto err;

	bdobj = bd_object(*vol);

	bdobj->btm_bd = bdev;
	bdobj->opened_by_bdev = true;

	ret = ocf_volume_open(*vol, NULL);
	if (ret)
		ocf_volume_destroy(*vol);

err:
	return ret;
}

void cas_blk_close_volume(ocf_volume_t vol)
{
	ocf_volume_close(vol);
	ocf_volume_deinit(vol);
	env_free(vol);
}

int _cas_blk_identify_type(const char *path, uint8_t *type)
{
	struct file *file;
	int result = 0;

	file = filp_open(path, O_RDONLY, 0);
	if (IS_ERR(file))
		return -OCF_ERR_INVAL_VOLUME_TYPE;

	if (S_ISBLK(CAS_FILE_INODE(file)->i_mode))
		*type = BLOCK_DEVICE_VOLUME;
	else
		result = -OCF_ERR_INVAL_VOLUME_TYPE;

	filp_close(file, 0);
	if (result)
		return result;

	return 0;
}

int cas_blk_identify_type(const char *path, uint8_t *type)
{
	return _cas_blk_identify_type(path, type);
}
