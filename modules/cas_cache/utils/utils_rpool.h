/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CAS_RPOOL_H__
#define __CAS_RPOOL_H__

#define CAS_RPOOL_MIN_SIZE_ITEM sizeof(struct list_head)

struct cas_reserve_pool;

typedef void (*cas_rpool_del)(void *allocator_ctx, void *item);
typedef void *(*cas_rpool_new)(void *allocator_ctx, int cpu);

struct cas_reserve_pool *cas_rpool_create(uint32_t limit, char *name,
		uint32_t item_size, cas_rpool_new rpool_new,
		cas_rpool_del rpool_del, void *allocator_ctx);

void cas_rpool_destroy(struct cas_reserve_pool *rpool,
		cas_rpool_del rpool_del, void *allocator_ctx);

void *cas_rpool_try_get(struct cas_reserve_pool *rpool, int *cpu);

int cas_rpool_try_put(struct cas_reserve_pool *rpool, void *item, int cpu);

#endif /* __CAS_RPOOL_H__ */

