/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_EXP_OBJ_H__
#define __CASDISK_EXP_OBJ_H__

#include <linux/kobject.h>
#include <linux/fs.h>

struct casdsk_disk;

struct casdsk_exp_obj_pt_io_ctx {
	struct casdsk_disk *dsk;
	struct bio *bio;
};

struct casdsk_exp_obj {

	struct gendisk *gd;
	struct request_queue *queue;

	struct block_device *locked_bd;

	struct module *owner;

	bool activated;

	struct casdsk_exp_obj_ops *ops;

	const char *dev_name;
	struct kobject kobj;

	atomic_t pt_ios;
	atomic_t *pending_rqs;
};

int __init casdsk_init_exp_objs(void);
void casdsk_deinit_exp_objs(void);

void casdsk_exp_obj_free(struct casdsk_disk *dsk);

int casdsk_exp_obj_detach(struct casdsk_disk *dsk);
int casdsk_exp_obj_attach(struct casdsk_disk *dsk, struct module *owner,
			struct casdsk_exp_obj_ops *ops);
void casdsk_exp_obj_prepare_pt(struct casdsk_disk *dsk);
void casdsk_exp_obj_prepare_attached(struct casdsk_disk *dsk);

void casdsk_exp_obj_prepare_shutdown(struct casdsk_disk *dsk);

static inline struct casdsk_exp_obj *casdsk_kobj_to_exp_obj(struct kobject *kobj)
{
	return container_of(kobj, struct casdsk_exp_obj, kobj);
}

#endif
