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

struct casdsk_disk {
	uint32_t id;
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

#endif
