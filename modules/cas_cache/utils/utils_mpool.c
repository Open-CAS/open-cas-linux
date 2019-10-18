/*
 * Copyright(c) 2012-2018 Intel Corporation
 * SPDX-License-Identifier: BSD-3-Clause-Clear
 */

#include "ocf_env.h"
#include "utils_mpool.h"


struct cas_mpool *cas_mpool_create(uint32_t hdr_size, uint32_t size, int flags,
		int mpool_max, const char *name_perfix)
{
	uint32_t i;
	char name[ALLOCATOR_NAME_MAX] = { '\0' };
	int result;
	struct cas_mpool *mpool;

	mpool = env_zalloc(sizeof(*mpool), ENV_MEM_NORMAL);
	if (!mpool)
		return NULL;

	mpool->item_size = size;
	mpool->hdr_size = hdr_size;
	mpool->flags = flags;

	for (i = 0; i < min(cas_mpool_max, mpool_max + 1); i++) {
		result = snprintf(name, sizeof(name), "%s_%u", name_perfix,
				(1 << i));
		if (result < 0 || result >= sizeof(name))
			goto err;

		mpool->allocator[i] = env_allocator_create(
				hdr_size + (size * (1 << i)), name);

		if (!mpool->allocator[i])
			goto err;
	}

	return mpool;

err:
	cas_mpool_destroy(mpool);
	return NULL;
}

void cas_mpool_destroy(struct cas_mpool *mallocator)
{
	if (mallocator) {
		uint32_t i;

		for (i = 0; i < cas_mpool_max; i++)
			if (mallocator->allocator[i])
				env_allocator_destroy(mallocator->allocator[i]);

		env_free(mallocator);
	}
}

static env_allocator *cas_mpool_get_allocator(
	struct cas_mpool *mallocator, uint32_t count)
{
	unsigned int idx;

	if (unlikely(count == 0))
		return cas_mpool_1;

	idx = 31 - __builtin_clz(count);

	if (__builtin_ffs(count) <= idx)
		idx++;

	if (idx >= cas_mpool_max)
		return NULL;

	return mallocator->allocator[idx];
}

void *cas_mpool_new_f(struct cas_mpool *mpool, uint32_t count, int flags)
{
	void *items = NULL;
	env_allocator *allocator;

	allocator = cas_mpool_get_allocator(mpool, count);

	if (allocator)
		items = env_allocator_new(allocator);
	else
		items = __vmalloc(mpool->hdr_size + (mpool->item_size * count),
				flags | __GFP_ZERO | __GFP_HIGHMEM,
				PAGE_KERNEL);

#ifdef ZERO_OR_NULL_PTR
	if (ZERO_OR_NULL_PTR(items))
		return NULL;
#endif

	return items;
}

void *cas_mpool_new(struct cas_mpool *mpool, uint32_t count)
{
	return cas_mpool_new_f(mpool, count, mpool->flags);
}

void cas_mpool_del(struct cas_mpool *mpool,
		void *items, uint32_t count)
{
	env_allocator *allocator;

	allocator = cas_mpool_get_allocator(mpool, count);

	if (allocator)
		env_allocator_del(allocator, items);
	else
		cas_vfree(items);
}
