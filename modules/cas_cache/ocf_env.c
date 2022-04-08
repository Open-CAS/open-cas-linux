/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "utils/utils_rpool.h"

/* *** ALLOCATOR *** */

#define CAS_ALLOC_ALLOCATOR_LIMIT 256

struct _env_allocator {
	/*!< Memory pool ID unique name */
	char *name;

	/*!< OS handle to memory pool */
	struct kmem_cache *kmem_cache;

	struct cas_reserve_pool *rpool;

	/*!< Size of specific item of memory pool */
	uint32_t item_size;

	/*!< Number of currently allocated items in pool */
	atomic_t count __attribute__((aligned(64)));
};

static inline size_t env_allocator_align(size_t size)
{
	if (size <= 2)
		return size;
	return (1ULL << 32) >> __builtin_clz(size - 1);
}

struct _env_allocator_item {
	uint32_t cpu : order_base_2(NR_CPUS);
	uint32_t from_rpool : 1;
	uint32_t used : 1;
	char data[] __attribute__ ((aligned (__alignof__(uint64_t))));
};

void *env_allocator_new(env_allocator *allocator)
{
	struct _env_allocator_item *item = NULL;
	int cpu = 0;

	if (allocator->rpool)
		item = cas_rpool_try_get(allocator->rpool, &cpu);

	if (item) {
		memset(item->data, 0, allocator->item_size -
			sizeof(struct _env_allocator_item));
		BUG_ON(item->used);
	} else {
		item = kmem_cache_zalloc(allocator->kmem_cache, GFP_NOIO);
	}

	if (item) {
		item->cpu = cpu;
		item->used = 1;
		atomic_inc(&allocator->count);
		return &item->data;
	} else {
		return NULL;
	}
}

static void *env_allocator_new_rpool(void *allocator_ctx, int cpu)
{
	env_allocator *allocator = (env_allocator*) allocator_ctx;
	struct _env_allocator_item *item;

	item = kmem_cache_zalloc(allocator->kmem_cache, GFP_NOIO | __GFP_NORETRY);

	if (item) {
		item->from_rpool = 1;
		item->cpu = cpu;
	}

	return item;
}

static void env_allocator_del_rpool(void *allocator_ctx, void *_item)
{
	struct _env_allocator_item *item = _item;
	env_allocator *allocator = (env_allocator* ) allocator_ctx;

	BUG_ON(item->used);

	kmem_cache_free(allocator->kmem_cache, item);
}

#define ENV_ALLOCATOR_NAME_MAX 128

env_allocator *env_allocator_create_extended(uint32_t size, const char *name,
	int rpool_limit)
{
	int error = -1;
	bool retry = true;

	env_allocator *allocator = kzalloc(sizeof(*allocator), GFP_KERNEL);
	if (!allocator) {
		error = __LINE__;
		goto err;
	}

	if (size < CAS_RPOOL_MIN_SIZE_ITEM) {
		printk(KERN_ERR "Can not create allocator."
				" Item size is too small.");
		ENV_WARN(true, OCF_PREFIX_SHORT" Can not create allocator."
				" Item size is too small.\n");
		error = __LINE__;
		goto err;
	}

	allocator->item_size = size + sizeof(struct _env_allocator_item);
	allocator->name = kstrdup(name, ENV_MEM_NORMAL);

	if (!allocator->name) {
		error = __LINE__;
		goto err;
	}

	/* Initialize kernel memory cache */
#ifdef CONFIG_SLAB
RETRY:
#else
	(void)retry;
#endif

	allocator->kmem_cache = kmem_cache_create(allocator->name,
			allocator->item_size, 0, 0, NULL);
	if (!allocator->kmem_cache) {
		/* Can not setup kernel memory cache */
		error = __LINE__;
		goto err;
	}

#ifdef CONFIG_SLAB
	if ((allocator->item_size < PAGE_SIZE)
			&& allocator->kmem_cache->gfporder) {
		/* Goal is to have one page allocation */
		if (retry) {
			retry = false;
			kmem_cache_destroy(allocator->kmem_cache);
			allocator->kmem_cache = NULL;
			allocator->item_size = env_allocator_align(allocator->item_size);
			goto RETRY;
		}
	}
#endif

	/* Initialize reserve pool handler per cpu */
	if (rpool_limit < 0)
		rpool_limit = CAS_ALLOC_ALLOCATOR_LIMIT;

	if (rpool_limit > 0) {
		allocator->rpool = cas_rpool_create(rpool_limit,
				allocator->name, allocator->item_size, env_allocator_new_rpool,
				env_allocator_del_rpool, allocator);
		if (!allocator->rpool) {
			error = __LINE__;
			goto err;
		}
	}

	return allocator;

err:
	printk(KERN_ERR "Cannot create memory allocator, ERROR %d", error);
	env_allocator_destroy(allocator);

	return NULL;
}

env_allocator *env_allocator_create(uint32_t size, const char *name, bool zero)
{
	return env_allocator_create_extended(size, name, -1);
}

void env_allocator_del(env_allocator *allocator, void *obj)
{
	struct _env_allocator_item *item =
		container_of(obj, struct _env_allocator_item, data);

	atomic_dec(&allocator->count);

	BUG_ON(!item->used);
	item->used = 0;

	if (item->from_rpool && !cas_rpool_try_put(allocator->rpool, item,
			item->cpu)) {
			return;
	}

	kmem_cache_free(allocator->kmem_cache, item);
}

void env_allocator_destroy(env_allocator *allocator)
{
	if (allocator) {
		if (allocator->rpool) {
			cas_rpool_destroy(allocator->rpool, env_allocator_del_rpool,
				allocator);
			allocator->rpool = NULL;
		}

		if (atomic_read(&allocator->count)) {
			printk(KERN_CRIT "Not all object deallocated\n");
			ENV_WARN(true, OCF_PREFIX_SHORT" Cleanup problem\n");
		}

		if (allocator->kmem_cache)
			kmem_cache_destroy(allocator->kmem_cache);

		kfree(allocator->name);
		kfree(allocator);
	}
}

uint32_t env_allocator_item_count(env_allocator *allocator)
{
	return atomic_read(&allocator->count);
}

static int env_sort_is_aligned(const void *base, int align)
{
	return IS_ENABLED(CONFIG_HAVE_EFFICIENT_UNALIGNED_ACCESS) ||
		((unsigned long)base & (align - 1)) == 0;
}

static void env_sort_u32_swap(void *a, void *b, int size)
{
	u32 t = *(u32 *)a;
	*(u32 *)a = *(u32 *)b;
	*(u32 *)b = t;
}

static void env_sort_u64_swap(void *a, void *b, int size)
{
	u64 t = *(u64 *)a;
	*(u64 *)a = *(u64 *)b;
	*(u64 *)b = t;
}

static void env_sort_generic_swap(void *a, void *b, int size)
{
	char t;

	do {
		t = *(char *)a;
		*(char *)a++ = *(char *)b;
		*(char *)b++ = t;
	} while (--size > 0);
}

void env_sort(void *base, size_t num, size_t size,
	int (*cmp_fn)(const void *, const void *),
	void (*swap_fn)(void *, void *, int size))
{
	/* pre-scale counters for performance */
	int64_t i = (num/2 - 1) * size, n = num * size, c, r;

	if (!swap_fn) {
		if (size == 4 && env_sort_is_aligned(base, 4))
			swap_fn = env_sort_u32_swap;
		else if (size == 8 && env_sort_is_aligned(base, 8))
			swap_fn = env_sort_u64_swap;
		else
			swap_fn = env_sort_generic_swap;
	}

	/* heapify */
	for ( ; i >= 0; i -= size) {
		for (r = i; r * 2 + size < n; r = c) {
			c = r * 2 + size;
			if (c < n - size &&
				cmp_fn(base + c, base + c + size) < 0)
				c += size;
			if (cmp_fn(base + r, base + c) >= 0)
				break;
			swap_fn(base + r, base + c, size);
		}
		env_cond_resched();
	}

	/* sort */
	for (i = n - size; i > 0; i -= size) {
		swap_fn(base, base + i, size);
		for (r = 0; r * 2 + size < i; r = c) {
			c = r * 2 + size;
			if (c < i - size &&
				cmp_fn(base + c, base + c + size) < 0)
				c += size;
			if (cmp_fn(base + r, base + c) >= 0)
				break;
			swap_fn(base + r, base + c, size);
		}
		env_cond_resched();
	}
}
