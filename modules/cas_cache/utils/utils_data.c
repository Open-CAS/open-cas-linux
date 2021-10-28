/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"

/**
 * This function locates index of IO vec from given vecs array where byte at
 * offset is located. When found it returns its index and byte offset within
 * this vec.
 * @param vecs IO vector array to be searched
 * @param vec_num number of items in IO vector array
 * @param offset byte offset to be found
 * @param offset_in_vec byte offset within found IO vec
 * @return vec index if it lies within specified buffer, otherwise -1
 */
static int get_starting_vec(struct bio_vec *vecs, uint64_t vecs_num,
		uint64_t offset, uint64_t *offset_in_vec)
{
	int i;

	for (i = 0; i < vecs_num; i++) {
		if (vecs[i].bv_len > offset) {
			if (offset_in_vec != NULL)
				*offset_in_vec = offset;
			return i;
		}
		offset -= vecs[i].bv_len;
	}

	return -1;
}

uint64_t cas_data_cpy(struct bio_vec *dst, uint64_t dst_num,
		struct bio_vec *src, uint64_t src_num,
		uint64_t to, uint64_t from, uint64_t bytes)
{
	uint64_t i, j, dst_len, src_len, to_copy;
	uint64_t dst_off, src_off;
	uint64_t written = 0;
	int ret;
	void *dst_p, *src_p;
	struct bio_vec *curr_dst, *curr_src;

	/* Locate vec idx and offset in dst vec array */
	ret = get_starting_vec(dst, dst_num, to, &to);
	if (ret < 0) {
		CAS_PRINT_RL(KERN_INFO "llu dst buffer too small "
				"to_offset=%llu bytes=%llu", to, bytes);
		return 0;
	}
	j = ret;

	/* Locate vec idx and offset in src vec array */
	ret = get_starting_vec(src, src_num, from, &from);
	if (ret < 0) {
		CAS_PRINT_RL(KERN_INFO "llu src buffer too small "
				"from_offset=%llu bytes=%llu", from, bytes);
		return 0;
	}
	i = ret;

	curr_dst = &dst[j];
	curr_src = &src[i];

	dst_off = curr_dst->bv_offset + to;
	dst_len = curr_dst->bv_len - to;

	src_off = curr_src->bv_offset + from;
	src_len = curr_src->bv_len - from;

	while (written < bytes) {
		dst_p = page_address(curr_dst->bv_page) + dst_off;
		src_p = page_address(curr_src->bv_page) + src_off;

		to_copy = src_len > dst_len ? dst_len : src_len;

		/* Prevent from copying too much*/
		if ((written + to_copy) > bytes)
			to_copy = bytes - written;

		memcpy(dst_p, src_p, to_copy);
		written += to_copy;

		if (written == bytes)
			break;

		/* Setup new len and offset. */
		dst_off += to_copy;
		dst_len -= to_copy;

		src_off += to_copy;
		src_len -= to_copy;

		/* Go to next src buffer */
		if (src_len == 0) {
			i++;

			/* Setup new len and offset. */
			if (i < src_num) {
				curr_src = &src[i];
				src_off = curr_src->bv_offset;
				src_len = curr_src->bv_len;
			} else {
				break;
			}
		}

		/* Go to next dst buffer */
		if (dst_len == 0) {
			j++;

			if (j < dst_num) {
				curr_dst = &dst[j];
				dst_off = curr_dst->bv_offset;
				dst_len = curr_dst->bv_len;
			} else {
				break;
			}
		}
	}

	if (written != bytes) {
		CAS_PRINT_RL(KERN_INFO "Written bytes not equal requested bytes "
			"(written=%llu; requested=%llu)", written, bytes);
	}

	return written;
}
