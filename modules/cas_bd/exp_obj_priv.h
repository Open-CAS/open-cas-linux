/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __CAS_BD_EXP_OBJ_PRIV_H__
#define __CAS_BD_EXP_OBJ_PRIV_H__

#include <linux/list.h>
#include <linux/mutex.h>
#include <linux/blk-mq.h>

#include "exp_obj.h"

struct cas_exp_obj {
	struct cas_disk *dsk;

	struct gendisk *gd;
	struct request_queue *queue;

	struct block_device *locked_bd;

	struct module *owner;

	struct cas_exp_obj_ops *ops;

	const char *dev_name;

	struct mutex openers_lock;
	unsigned int openers;
	bool claimed;

	int minor_slot;

	struct blk_mq_tag_set tag_set;

	bool frozen;

	void *private;
};

int __init cas_init_exp_objs(void);

void cas_deinit_exp_objs(void);

#endif
