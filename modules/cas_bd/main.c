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

static ssize_t delete_store(struct kobject *kobj, struct kobj_attribute *attr,
		const char *buf, size_t count)
{
	char dev_name[DISK_NAME_LEN];
	int result;
	size_t len;

	len = strscpy(dev_name, buf, sizeof(dev_name));
	if (len <= 0)
		return -EINVAL;

	while (len > 0 && dev_name[len - 1] == '\n')
		dev_name[--len] = '\0';

	result = cas_exp_obj_box_delete(dev_name);
	if (result)
		return result;

	return count;
}

static struct kobj_attribute delete_attr =
		__ATTR(delete, 0200, NULL, delete_store);

static int __init cas_bd_init_module(void)
{
	int result = 0;

	result = cas_init_exp_objs();
	if (result)
		return result;

	result = cas_init_disks();
	if (result)
		goto error_init_disks;

	result = sysfs_create_file(&THIS_MODULE->mkobj.kobj, &delete_attr.attr);
	if (result)
		goto error_sysfs;

	printk(KERN_INFO "Open Cache Acceleration Software Linux"
		" Version %s (%s)::Module cas_disk loaded successfully\n",
		CAS_VERSION, CAS_KERNEL);

	return 0;

error_sysfs:
	cas_deinit_disks();
error_init_disks:
	cas_deinit_exp_objs();

	return result;
}

module_init(cas_bd_init_module);

static void __exit cas_bd_exit_module(void)
{
	sysfs_remove_file(&THIS_MODULE->mkobj.kobj, &delete_attr.attr);
	cas_deinit_disks();
	cas_deinit_exp_objs();
}

module_exit(cas_bd_exit_module);

MODULE_AUTHOR("Intel(R) Corporation");
MODULE_AUTHOR("Unvertical");
MODULE_LICENSE("Dual BSD/GPL");
MODULE_DESCRIPTION("Open CAS block device module");
MODULE_VERSION(CAS_VERSION);
