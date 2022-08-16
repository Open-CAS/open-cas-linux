/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/


#ifndef __CONTEXT_H__
#define __CONTEXT_H__

#include "linux_kernel_version.h"

struct bio_vec_iter {
	struct bio_vec *vec;
	uint32_t vec_size;
	uint32_t idx;
	uint32_t offset;
	uint32_t len;
	struct bio_vec *ivec;
};

struct blk_data {
	/**
	 * @brief Atomic counter for core device
	 */
	atomic_t master_remaining;

	/**
	 * @brief Master bio request
	 */
	struct bio *bio;

	/**
	 * @brief Size of master request
	 */
	uint32_t master_size;

	/**
	 * @brief CAS IO with which data is associated
	 */
	struct ocf_io *io;

	/**
	 * @brief Timestamp of start processing request
	 */
	unsigned long long start_time;

	/**
	 * @brief Request data siz
	 */
	uint32_t size;

	/**
	 * @brief This filed indicates an error for request
	 */
	int error;

	/**
	 * @brief Iterator for accessing data
	 */
	struct bio_vec_iter iter;

	/**
	 * @brief Request data
	 */
	struct bio_vec vec[];
};

struct blk_data *cas_alloc_blk_data(uint32_t size, gfp_t flags);
void cas_free_blk_data(struct blk_data *data);

ctx_data_t *cas_ctx_data_alloc(uint32_t pages);
ctx_data_t *cas_ctx_data_zalloc(uint32_t pages);
void cas_ctx_data_free(ctx_data_t *ctx_data);
void cas_ctx_data_secure_erase(ctx_data_t *ctx_data);

int cas_initialize_context(void);
void cas_cleanup_context(void);

#endif /* __CONTEXT_H__ */
