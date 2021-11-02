/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "utils_gc.h"
#include <linux/vmalloc.h>

#if defined (CAS_GARBAGE_COLLECTOR)

struct cas_vfree_item {
	struct llist_head list;
	struct work_struct ws;
};

static DEFINE_PER_CPU(struct cas_vfree_item, cas_vfree_item);

static atomic_t freed = ATOMIC_INIT(0);

static void cas_garbage_collector(struct work_struct *w)
{
        struct cas_vfree_item *item = container_of(w, struct cas_vfree_item,
			ws);
	struct llist_node *llnode = llist_del_all(&item->list);

	while (llnode) {
		void *item = llnode;

		llnode = llnode->next;
		atomic_dec(&freed);
		vfree(item);
	}
}

void cas_vfree(const void *addr)
{
	struct cas_vfree_item *item = this_cpu_ptr(&cas_vfree_item);

	if (!addr)
		return;

	atomic_inc(&freed);

	if (llist_add((struct llist_node *)addr, &item->list))
		schedule_work(&item->ws);
}

void cas_garbage_collector_init(void)
{
	int i;

	for_each_possible_cpu(i) {
		struct cas_vfree_item *item;

		item = &per_cpu(cas_vfree_item, i);
		init_llist_head(&item->list);
		INIT_WORK(&item->ws, cas_garbage_collector);
	}
}

void cas_garbage_collector_deinit(void)
{
	int i;

	for_each_possible_cpu(i) {
		struct cas_vfree_item *item;

		item = &per_cpu(cas_vfree_item, i);
		while (work_pending(&item->ws))
			schedule();
	}

	WARN(atomic_read(&freed) != 0,
			OCF_PREFIX_SHORT" Not all memory deallocated\n");
}
#else
void cas_garbage_collector_init(void) {};

void cas_garbage_collector_deinit(void) {};

void cas_vfree(const void *addr) { vfree(addr); };
#endif
