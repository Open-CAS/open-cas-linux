/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <linux/module.h>
#include <linux/blkdev.h>
#include <linux/blk-mq.h>
#include <linux/vmalloc.h>

#include "exp_obj_priv.h"
#include "disk_priv.h"
#include "exp_obj_box_priv.h"

static LIST_HEAD(box_list);
static DEFINE_MUTEX(box_mutex);

void cas_exp_obj_box_deposit(struct cas_exp_obj *exp_obj)
{
	mutex_lock(&box_mutex);
	list_add_tail(&exp_obj->list, &box_list);
	__module_get(THIS_MODULE);
	module_put(exp_obj->owner);
	exp_obj->owner = THIS_MODULE;
	mutex_unlock(&box_mutex);
}
EXPORT_SYMBOL(cas_exp_obj_box_deposit);

struct cas_exp_obj *cas_exp_obj_box_claim(struct cas_disk *dsk,
		struct module *owner, struct cas_exp_obj_ops *ops, void *priv)
{
	struct cas_exp_obj *exp_obj;

	if (!try_module_get(owner))
		return ERR_PTR(-ENAVAIL);

	mutex_lock(&box_mutex);
	list_for_each_entry(exp_obj, &box_list, list) {
		if (exp_obj->dsk == dsk) {
			list_del(&exp_obj->list);
			module_put(exp_obj->owner);
			exp_obj->owner = owner;
			exp_obj->ops = ops;
			exp_obj->private = priv;
			mutex_unlock(&box_mutex);
			return exp_obj;
		}
	}
	mutex_unlock(&box_mutex);

	module_put(owner);

	return ERR_PTR(-ENODEV);
}
EXPORT_SYMBOL(cas_exp_obj_box_claim);

int cas_exp_obj_box_delete(const char *dev_name)
{
	struct cas_exp_obj *exp_obj;

	mutex_lock(&box_mutex);
	list_for_each_entry(exp_obj, &box_list, list) {
		if (!strcmp(exp_obj->dev_name, dev_name)) {
			list_del(&exp_obj->list);
			mutex_unlock(&box_mutex);
			cas_exp_obj_set_error(exp_obj);
			if (cas_exp_obj_is_frozen(exp_obj))
				cas_exp_obj_unfreeze_queue(exp_obj);
			cas_exp_obj_dismantle(exp_obj);
			cas_exp_obj_destroy(exp_obj);
			return 0;
		}
	}
	mutex_unlock(&box_mutex);

	return -ENODEV;
}
