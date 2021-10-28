/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <linux/module.h>
#include <linux/fs.h>
#include <linux/vmalloc.h>
#include "cas_disk_defs.h"
#include "cas_disk.h"
#include "disk.h"
#include "exp_obj.h"
#include "sysfs.h"

/* Layer information. */
MODULE_AUTHOR("Intel(R) Corporation");
MODULE_LICENSE("Dual BSD/GPL");
MODULE_VERSION(CAS_VERSION);

static int iface_version = CASDSK_IFACE_VERSION;
module_param(iface_version, int, (S_IRUSR | S_IRGRP));

struct casdsk_module *casdsk_module;

uint32_t casdsk_get_version(void)
{
	return CASDSK_IFACE_VERSION;
}
EXPORT_SYMBOL(casdsk_get_version);

static void _casdsk_module_release(struct kobject *kobj)
{
	struct casdsk_module *mod;

	CASDSK_DEBUG_TRACE();

	BUG_ON(!kobj);

	mod = container_of(kobj, struct casdsk_module, kobj);
	BUG_ON(!mod);

	kfree(mod);
}

static struct kobj_type _casdsk_module_ktype = {
	.release = _casdsk_module_release,
};

static int __init casdsk_init_kobjects(void)
{
	int result = 0;

	CASDSK_DEBUG_TRACE();

	kobject_init(&casdsk_module->kobj, &_casdsk_module_ktype);
	result = kobject_add(&casdsk_module->kobj, kernel_kobj, "cas_disk");
	if (result)
		CASDSK_DEBUG_ERROR("Cannot register kobject");

	return result;
}

static int __init casdsk_init_module(void)
{
	int result = 0;

	casdsk_module = kzalloc(sizeof(*casdsk_module), GFP_KERNEL);
	if (!casdsk_module) {
		result = -ENOMEM;
		goto error_kmalloc;
	}

	mutex_init(&casdsk_module->lock);

	mutex_lock(&casdsk_module->lock);

	result = casdsk_init_exp_objs();
	if (result)
		goto error_init_exp_objs;

	result = casdsk_init_disks();
	if (result)
		goto error_init_disks;

	result = casdsk_init_kobjects();
	if (result)
		goto error_kobjects;

	mutex_unlock(&casdsk_module->lock);

	printk(CASDSK_KERN_INFO "%s Version %s (%s)::Module loaded successfully\n",
		CASDSK_LOGO, CAS_VERSION, CAS_KERNEL);

	return result;

error_kobjects:
	casdsk_deinit_disks();
error_init_disks:
	casdsk_deinit_exp_objs();
error_init_exp_objs:
	mutex_unlock(&casdsk_module->lock);
	kfree(casdsk_module);
error_kmalloc:
	return result;
}
module_init(casdsk_init_module);

static void __exit casdsk_deinit_kobjects(void)
{
	kobject_put(&casdsk_module->kobj);
}

static void __exit casdsk_exit_module(void)
{
	casdsk_disk_shutdown_all();
	casdsk_deinit_disks();
	casdsk_deinit_exp_objs();
	casdsk_deinit_kobjects();
}
module_exit(casdsk_exit_module);
