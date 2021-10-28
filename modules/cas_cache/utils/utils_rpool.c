/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "ocf/ocf.h"
#include "utils_rpool.h"
#include "ocf_env.h"
#include "../cas_cache.h"

#define CAS_UTILS_RPOOL_DEBUG 0
#if 1 == CAS_UTILS_RPOOL_DEBUG
#define CAS_DEBUG_TRACE() \
	printk(KERN_INFO "[Utils][RPOOL] %s\n", __func__)

#define CAS_DEBUG_MSG(msg) \
	printk(KERN_INFO "[Utils][RPOOL] %s - %s\n", __func__, msg)

#define CAS_DEBUG_PARAM(format, ...) \
	printk(KERN_INFO "[Utils][RPOOL] %s - "format"\n", \
			__func__, ##__VA_ARGS__)
#else
#define CAS_DEBUG_TRACE()
#define CAS_DEBUG_MSG(msg)
#define CAS_DEBUG_PARAM(format, ...)
#endif

/* This is currently 24B padded/force aligned to 32B.
 * With a 64B cacheline this means two structs on different cores may
 * invalidate each other. This shouldn't happen between different physical
 * CPUs and cause false sharing though, since with an even number of cores
 * per CPU same cacheline shouldn't be polluted from the other physical CPU.
 * */
struct _cas_reserve_pool_per_cpu {
	spinlock_t lock;
	struct list_head list;
	atomic_t count;
} __attribute__((__aligned__(32)));

struct cas_reserve_pool {
	uint32_t limit;
	uint32_t entry_size;
	char *name;
	struct _cas_reserve_pool_per_cpu *rpools;
};

struct _cas_rpool_pre_alloc_info {
	struct work_struct ws;
	struct completion cmpl;
	struct cas_reserve_pool *rpool_master;
	cas_rpool_new rpool_new;
	void *allocator_ctx;
	int error;
};

#define RPOOL_ITEM_TO_ENTRY(rpool, item) \
		(void *)((unsigned long)item + sizeof(struct list_head) \
				- rpool->entry_size)

#define RPOOL_ENTRY_TO_ITEM(rpool, entry) \
		(struct list_head *)((unsigned long)entry + rpool->entry_size \
				- sizeof(struct list_head))

void _cas_rpool_pre_alloc_do(struct work_struct *ws)
{
	struct _cas_rpool_pre_alloc_info *info =
			container_of(ws, struct _cas_rpool_pre_alloc_info, ws);
	struct cas_reserve_pool *rpool_master = info->rpool_master;
	struct _cas_reserve_pool_per_cpu *current_rpool;
	struct list_head *item;
	void *entry;
	int i, cpu;

	CAS_DEBUG_TRACE();

	cpu = smp_processor_id();
	current_rpool = &rpool_master->rpools[cpu];

	for (i = 0; i < rpool_master->limit; i++) {
		entry = info->rpool_new(info->allocator_ctx, cpu);
		if (!entry) {
			info->error = -ENOMEM;
			complete(&info->cmpl);
			return;
		}
		item = RPOOL_ENTRY_TO_ITEM(rpool_master, entry);
		list_add_tail(item, &current_rpool->list);
		atomic_inc(&current_rpool->count);
	}

	CAS_DEBUG_PARAM("Added [%d] pre allocated items to reserve poll [%s]"
			" for cpu %d", atomic_read(&current_rpool->count),
			rpool_master->name, cpu);

	complete(&info->cmpl);
}


int _cas_rpool_pre_alloc_schedule(int cpu,
		struct _cas_rpool_pre_alloc_info *info)
{
	init_completion(&info->cmpl);
	INIT_WORK(&info->ws, _cas_rpool_pre_alloc_do);
	schedule_work_on(cpu, &info->ws);
	schedule();

	wait_for_completion(&info->cmpl);
	return info->error;
}

void cas_rpool_destroy(struct cas_reserve_pool *rpool_master,
		cas_rpool_del rpool_del, void *allocator_ctx)
{
	int i, cpu_no = num_online_cpus();
	struct _cas_reserve_pool_per_cpu *current_rpool = NULL;
	struct list_head *item = NULL, *next = NULL;
	void *entry;

	CAS_DEBUG_TRACE();

	if (!rpool_master)
		return;

	if (!rpool_master->rpools) {
		kfree(rpool_master);
		return;
	}

	for (i = 0; i < cpu_no; i++) {
		current_rpool = &rpool_master->rpools[i];

		CAS_DEBUG_PARAM("Destroyed reserve poll [%s] for cpu %d",
				rpool_master->name, i);

		if (!atomic_read(&current_rpool->count))
			continue;

		list_for_each_safe(item, next, &current_rpool->list) {
			entry = RPOOL_ITEM_TO_ENTRY(rpool_master, item);
			list_del(item);
			rpool_del(allocator_ctx, entry);
			atomic_dec(&current_rpool->count);
		}

		if (atomic_read(&current_rpool->count)) {
			printk(KERN_CRIT "Not all object from reserve poll"
				"[%s] deallocated\n", rpool_master->name);
			WARN(true, OCF_PREFIX_SHORT" Cleanup problem\n");
		}
	}

	kfree(rpool_master->rpools);
	kfree(rpool_master);
}

struct cas_reserve_pool *cas_rpool_create(uint32_t limit, char *name,
		uint32_t entry_size, cas_rpool_new rpool_new,
		cas_rpool_del rpool_del, void *allocator_ctx)
{
	int i, cpu_no = num_online_cpus();
	struct cas_reserve_pool *rpool_master = NULL;
	struct _cas_reserve_pool_per_cpu *current_rpool = NULL;
	struct _cas_rpool_pre_alloc_info info;

	CAS_DEBUG_TRACE();

	memset(&info, 0, sizeof(info));

	rpool_master = kzalloc(sizeof(*rpool_master), GFP_KERNEL);
	if (!rpool_master)
		goto error;

	rpool_master->rpools = kzalloc(sizeof(*rpool_master->rpools) * cpu_no,
			GFP_KERNEL);
	if (!rpool_master->rpools)
		goto error;

	rpool_master->limit = limit;
	rpool_master->name = name;
	rpool_master->entry_size = entry_size;

	info.rpool_master = rpool_master;
	info.rpool_new = rpool_new;
	info.allocator_ctx = allocator_ctx;

	for (i = 0; i < cpu_no; i++) {
		current_rpool = &rpool_master->rpools[i];
		spin_lock_init(&current_rpool->lock);
		INIT_LIST_HEAD(&current_rpool->list);

		if (_cas_rpool_pre_alloc_schedule(i, &info))
			goto error;

		CAS_DEBUG_PARAM("Created reserve poll [%s] for cpu %d",
				rpool_master->name, i);
	}

	return rpool_master;
error:

	cas_rpool_destroy(rpool_master, rpool_del, allocator_ctx);
	return NULL;
}

#define LIST_FIRST_ITEM(head) head.next

void *cas_rpool_try_get(struct cas_reserve_pool *rpool_master, int *cpu)
{
	unsigned long flags;
	struct _cas_reserve_pool_per_cpu *current_rpool = NULL;
	struct list_head *item = NULL;
	void *entry = NULL;

	CAS_DEBUG_TRACE();

	*cpu = smp_processor_id();
	current_rpool = &rpool_master->rpools[*cpu];

	spin_lock_irqsave(&current_rpool->lock, flags);

	if (!list_empty(&current_rpool->list)) {
		item = LIST_FIRST_ITEM(current_rpool->list);
		entry = RPOOL_ITEM_TO_ENTRY(rpool_master, item);
		list_del(item);
		atomic_dec(&current_rpool->count);
	}

	spin_unlock_irqrestore(&current_rpool->lock, flags);

	CAS_DEBUG_PARAM("[%s]Removed item from reserve pool [%s] for cpu [%d], "
				"items in pool %d", rpool_master->name,
				item == NULL ? "SKIPPED" : "OK", *cpu,
				atomic_read(&current_rpool->count));

	return entry;
}

int cas_rpool_try_put(struct cas_reserve_pool *rpool_master, void *entry, int cpu)
{
	int ret = 0;
	unsigned long flags;
	struct _cas_reserve_pool_per_cpu *current_rpool = NULL;
	struct list_head *item;

	CAS_DEBUG_TRACE();

	current_rpool = &rpool_master->rpools[cpu];

	spin_lock_irqsave(&current_rpool->lock, flags);

	if (atomic_read(&current_rpool->count) >= rpool_master->limit) {
		ret = 1;
		goto error;
	}

	item = RPOOL_ENTRY_TO_ITEM(rpool_master, entry);
	list_add_tail(item, &current_rpool->list);

	atomic_inc(&current_rpool->count);

error:
	CAS_DEBUG_PARAM("[%s]Added item to reserve pool [%s] for cpu [%d], "
				"items in pool %d", rpool_master->name,
				ret == 1 ? "SKIPPED" : "OK", cpu,
				atomic_read(&current_rpool->count));
	spin_unlock_irqrestore(&current_rpool->lock, flags);
	return ret;
}
