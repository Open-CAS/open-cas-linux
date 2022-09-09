/*
 * Copyright(c) 2012-2022 Intel Corporation
 * SPDX-License-Identifier: BSD-3-Clause
 */
#ifndef __CASDISK_DEFS_H__
#define __CASDISK_DEFS_H__

#include <linux/version.h>
#include <linux/fs.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/kobject.h>
#include <linux/blkdev.h>

struct casdsk_module {
	struct mutex lock;

	struct list_head disk_list;
	uint32_t next_disk_id;
	int disk_major;
	int next_minor;

	struct kmem_cache *disk_cache;
	struct kmem_cache *exp_obj_cache;

	struct kobject kobj;
};

extern struct casdsk_module *casdsk_module;

#include "debug.h"

#endif
