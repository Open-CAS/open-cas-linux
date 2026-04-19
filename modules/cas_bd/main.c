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

static int __init cas_bd_init_module(void)
{
	int result = 0;

	result = cas_init_exp_objs();
	if (result)
		return result;

	result = cas_init_disks();
	if (result)
		goto error_init_disks;

	printk(KERN_INFO "Open Cache Acceleration Software Linux"
		" Version %s (%s)::Module cas_disk loaded successfully\n",
		CAS_VERSION, CAS_KERNEL);

	return 0;

error_init_disks:
	cas_deinit_exp_objs();

	return result;
}

module_init(cas_bd_init_module);

static void __exit cas_bd_exit_module(void)
{
	cas_deinit_disks();
	cas_deinit_exp_objs();
}

module_exit(cas_bd_exit_module);

MODULE_AUTHOR("Intel(R) Corporation");
MODULE_AUTHOR("Unvertical");
MODULE_LICENSE("Dual BSD/GPL");
MODULE_DESCRIPTION("Open CAS block device module");
MODULE_VERSION(CAS_VERSION);
