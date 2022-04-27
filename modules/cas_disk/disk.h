/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __
#define __CASDISK_DISK_H__

#include <linux/kobject.h>
#include <linux/fs.h>
#include <linux/blkdev.h>
#include <linux/mutex.h>
#include <linux/blk-mq.h>

struct casdsk_exp_obj;

#define CASDSK_MODE_UNKNOWN		0
#define CASDSK_MODE_PT			(1 << 0)
#define CASDSK_MODE_ATTACHED		(1 << 1)
#define CASDSK_MODE_SHUTDOWN		(1 << 2)
#define CASDSK_MODE_TRANSITION		(1 << 3)
#define CASDSK_MODE_TRANS_TO_ATTACHED	(CASDSK_MODE_PT | CASDSK_MODE_TRANSITION)
#define CASDSK_MODE_TRANS_TO_PT		(CASDSK_MODE_ATTACHED | \
		CASDSK_MODE_TRANSITION)
#define CASDSK_MODE_TRANS_TO_SHUTDOWN	(CASDSK_MODE_SHUTDOWN | \
		CASDSK_MODE_TRANSITION)

struct casdsk_disk {
	uint32_t id;
	atomic_t mode;
	char *path;

	struct mutex lock;

	struct mutex openers_lock;
	unsigned int openers;
	bool claimed;

	struct block_device *bd;

	int gd_flags;
	int gd_minors;

	struct blk_mq_tag_set tag_set;
	struct casdsk_exp_obj *exp_obj;

	struct kobject kobj;
	struct list_head list;

	void *private;
};

int __init casdsk_init_disks(void);
void casdsk_deinit_disks(void);

void __exit casdsk_disk_shutdown_all(void);

int casdsk_disk_allocate_minors(int count);

static inline void casdsk_disk_lock(struct casdsk_disk *dsk)
{
	mutex_lock(&dsk->lock);
}

static inline void casdsk_disk_unlock(struct casdsk_disk *dsk)
{
	mutex_unlock(&dsk->lock);
}

static inline struct casdsk_disk *casdsk_kobj_to_disk(struct kobject *kobj)
{
	return container_of(kobj, struct casdsk_disk, kobj);
}

static inline bool casdsk_disk_in_transition(struct casdsk_disk *dsk)
{
	return (atomic_read(&dsk->mode) & CASDSK_MODE_TRANSITION) ==
			CASDSK_MODE_TRANSITION;
}

static inline bool casdsk_disk_is_attached(struct casdsk_disk *dsk)
{
	return (atomic_read(&dsk->mode) & CASDSK_MODE_ATTACHED) ==
			CASDSK_MODE_ATTACHED;
}

static inline bool casdsk_disk_is_pt(struct casdsk_disk *dsk)
{
	return (atomic_read(&dsk->mode) & CASDSK_MODE_PT) == CASDSK_MODE_PT;
}

static inline bool casdsk_disk_is_shutdown(struct casdsk_disk *dsk)
{
	return (atomic_read(&dsk->mode) & CASDSK_MODE_SHUTDOWN) ==
			CASDSK_MODE_SHUTDOWN;
}

static inline bool casdsk_disk_is_unknown(struct casdsk_disk *dsk)
{
	return atomic_read(&dsk->mode) == CASDSK_MODE_UNKNOWN;
}

#endif
