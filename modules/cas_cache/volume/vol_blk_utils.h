/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLK_UTILS_H__
#define __VOL_BLK_UTILS_H__

#include "obj_blk.h"
#include "context.h"

struct blkio {
	int error;
	atomic_t rq_remaning;
	atomic_t ref_counter;
	int32_t dir;

	struct blk_data *data; /* IO data buffer */

	/* BIO vector iterator for sending IO */
	struct bio_vec_iter iter;
};

static inline struct blkio *cas_io_to_blkio(struct ocf_io *io)
{
	return ocf_io_get_priv(io);
}

int cas_blk_io_set_data(struct ocf_io *io, ctx_data_t *data,
		uint32_t offset);
ctx_data_t *cas_blk_io_get_data(struct ocf_io *io);

int cas_blk_open_volume_by_bdev(ocf_volume_t *vol,
		struct block_device *bdev);
void cas_blk_close_volume(ocf_volume_t vol);

int cas_blk_identify_type(const char *path, uint8_t *type);

static inline void cas_io_iter_init(struct bio_vec_iter *iter,
		struct bio_vec *vec, uint32_t vec_size)
{
	iter->vec = iter->ivec = vec;
	iter->vec_size = vec_size;
	iter->idx = 0;
	iter->offset = vec->bv_offset;
	iter->len = vec->bv_len;
}

static inline void cas_io_iter_set(struct bio_vec_iter *iter,
		struct bio_vec *vec, uint32_t vec_size,
		uint32_t idx, uint32_t offset, uint32_t len)
{
	iter->vec = vec;
	iter->vec_size = vec_size;
	iter->idx = idx;
	iter->offset = offset;
	iter->len = len;

	if (iter->idx < vec_size) {
		iter->ivec = &vec[iter->idx];
	} else {
		iter->ivec = NULL;
		WARN(1, "Setting offset out of BIO vector");
	}
}

static inline void cas_io_iter_copy_set(struct bio_vec_iter *dst,
		struct bio_vec_iter *src)
{
	dst->vec = src->vec;
	dst->vec_size = src->vec_size;
	dst->idx = src->idx;
	dst->offset = src->offset;
	dst->len = src->len;
	dst->ivec = src->ivec;
}

static inline bool cas_io_iter_is_next(struct bio_vec_iter *iter)
{
	return iter->idx < iter->vec_size ? true : false;
	/* TODO UNITTEST */
}

static inline uint32_t cas_io_iter_size_done(struct bio_vec_iter *iter)
{
	return iter->idx;
	/* TODO UNITTEST */
}

static inline uint32_t cas_io_iter_size_left(struct bio_vec_iter *iter)
{
	if (iter->idx < iter->vec_size)
		return min(iter->vec_size - iter->idx, CAS_BIO_MAX_VECS);
	return 0;
	/* TODO UNITTEST */
}

static inline uint32_t cas_io_iter_current_offset(struct bio_vec_iter *iter)
{
	return iter->idx < iter->vec_size ? iter->offset : 0;
	/* TODO UNITTEST */
}

static inline uint32_t cas_io_iter_current_length(struct bio_vec_iter *iter)
{
	return iter->idx < iter->vec_size ? iter->len : 0;
	/* TODO UNITTEST */
}

static inline struct page *cas_io_iter_current_page(struct bio_vec_iter *iter)
{
	return iter->idx < iter->vec_size ? iter->ivec->bv_page : NULL;
	/* TODO UNITTEST */
}

uint32_t cas_io_iter_cpy(struct bio_vec_iter *dst, struct bio_vec_iter *src,
		uint32_t bytes);

uint32_t cas_io_iter_cpy_from_data(struct bio_vec_iter *dst,
		const void *src, uint32_t bytes);

uint32_t cas_io_iter_cpy_to_data(void *dst, struct bio_vec_iter *src,
		uint32_t bytes);

uint32_t cas_io_iter_move(struct bio_vec_iter *iter,
		uint32_t bytes);

uint32_t cas_io_iter_zero(struct bio_vec_iter *iter, uint32_t bytes);

#endif /* __VOL_BLK_UTILS_H__ */
