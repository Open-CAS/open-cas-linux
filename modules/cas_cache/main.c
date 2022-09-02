/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"

/* Layer information. */
MODULE_AUTHOR("Intel(R) Corporation");
MODULE_LICENSE("Dual BSD/GPL");
MODULE_VERSION(CAS_VERSION);

u32 max_writeback_queue_size = 65536;
module_param(max_writeback_queue_size, uint, (S_IRUSR | S_IRGRP));
MODULE_PARM_DESC(max_writeback_queue_size,
		"Max cache writeback queue size (65536)");

u32 writeback_queue_unblock_size = 60000;
module_param(writeback_queue_unblock_size, uint, (S_IRUSR | S_IRGRP));
MODULE_PARM_DESC(writeback_queue_unblock_size,
		"Cache writeback queue size (60000) at which queue "
		"is unblocked when blocked");

u32 use_io_scheduler = 1;
module_param(use_io_scheduler, uint, (S_IRUSR | S_IRGRP));
MODULE_PARM_DESC(use_io_scheduler,
		"Configure how IO shall be handled. "
		"0 - in make request function, 1 - in request function");

u32 unaligned_io = 1;
module_param(unaligned_io, uint, (S_IRUSR | S_IRGRP));
MODULE_PARM_DESC(unaligned_io,
		"Define how to handle I/O requests unaligned to 4 kiB, "
		"0 - apply PT, 1 - handle by cache");

u32 seq_cut_off_mb = 1;
module_param(seq_cut_off_mb, uint, (S_IRUSR | S_IRGRP));
MODULE_PARM_DESC(seq_cut_off_mb,
		"Sequential cut off threshold in MiB. 0 - disable");

/* globals */
ocf_ctx_t cas_ctx;
struct casdsk_module cas_module;
struct casdsk_module *casdsk_module;

static int __init cas_init_module(void)
{
	int result = 0;

	if (!writeback_queue_unblock_size || !max_writeback_queue_size) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Invalid module parameter.\n");
		return -EINVAL;
	}

	if (writeback_queue_unblock_size >= max_writeback_queue_size) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"parameter writeback_queue_unblock_size"
				" must be less than max_writeback_queue_size\n");
		return -EINVAL;
	}

	if (unaligned_io != 0 && unaligned_io != 1) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Invalid value for unaligned_io parameter\n");
		return -EINVAL;
	}

	if (use_io_scheduler != 0 && use_io_scheduler != 1) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Invalid value for use_io_scheduler parameter\n");
		return -EINVAL;
	}

	casdsk_module = &cas_module;

	result = casdsk_init_exp_objs();
	if (result)
		return result;

	result = casdsk_init_disks();
	if (result)
		goto error_init_disks;

	result = cas_initialize_context();
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Cannot initialize cache library\n");
		goto error_init_context;
	}

	result = cas_ctrl_device_init();
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Cannot initialize control device\n");
		goto error_init_device;
	}

	printk(KERN_INFO "%s Version %s (%s)::Module loaded successfully\n",
		OCF_PREFIX_LONG, CAS_VERSION, CAS_KERNEL);

	return 0;

error_init_device:
	cas_cleanup_context();
error_init_context:
	casdsk_deinit_disks();
error_init_disks:
	casdsk_deinit_exp_objs();

	return result;
}

module_init(cas_init_module);

static void __exit cas_exit_module(void)
{
	cas_ctrl_device_deinit();
	cas_cleanup_context();
	casdsk_deinit_disks();
	casdsk_deinit_exp_objs();
}

module_exit(cas_exit_module);
