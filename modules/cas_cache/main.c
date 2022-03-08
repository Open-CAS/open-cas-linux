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
struct casdsk_functions_mapper casdisk_functions;

#if defined(SYMBOL_LOOKUP_SUPPORTED) && defined(MODULE_MUTEX_SUPPORTED)

struct exported_symbol {
	char *name;
	unsigned long addr;
};

int static cas_find_symbol(void *data, const char *namebuf,
		struct module *module, unsigned long kallsyms_addresses)
{
	struct exported_symbol *sym = data;

	if (strcmp(namebuf, sym->name) == 0)
		sym->addr = kallsyms_addresses;
	return 0;
}

#define cas_lookup_symbol(f) ({ \
	struct exported_symbol sym = {#f, 0}; \
	kallsyms_on_each_symbol(&cas_find_symbol, &sym); \
	casdisk_functions.f = (void *)sym.addr; \
        if (!casdisk_functions.f)  \
             return -EINVAL; \
})

#else

#include "../cas_disk/cas_disk.h"
#include "../cas_disk/exp_obj.h"
#define cas_lookup_symbol(f) ({ \
	casdisk_functions.f = (void *)f; \
})

#endif

int static cas_casdisk_lookup_funtions(void)
{
#ifdef MODULE_MUTEX_SUPPORTED
	mutex_lock(&module_mutex);
#endif
	cas_lookup_symbol(casdsk_disk_detach);
	cas_lookup_symbol(casdsk_exp_obj_destroy);
	cas_lookup_symbol(casdsk_exp_obj_create);
	cas_lookup_symbol(casdsk_exp_obj_free);
	cas_lookup_symbol(casdsk_disk_get_queue);
	cas_lookup_symbol(casdsk_disk_get_blkdev);
	cas_lookup_symbol(casdsk_exp_obj_get_queue);
	cas_lookup_symbol(casdsk_get_version);
	cas_lookup_symbol(casdsk_disk_close);
	cas_lookup_symbol(casdsk_disk_claim);
	cas_lookup_symbol(casdsk_exp_obj_unlock);
	cas_lookup_symbol(casdsk_disk_set_pt);
	cas_lookup_symbol(casdsk_disk_get_gendisk);
	cas_lookup_symbol(casdsk_disk_attach);
	cas_lookup_symbol(casdsk_disk_set_attached);
	cas_lookup_symbol(casdsk_exp_obj_activate);
	cas_lookup_symbol(casdsk_exp_obj_activated);
	cas_lookup_symbol(casdsk_exp_obj_lock);
	cas_lookup_symbol(casdsk_disk_open);
	cas_lookup_symbol(casdsk_disk_clear_pt);
	cas_lookup_symbol(casdsk_exp_obj_get_gendisk);
#ifdef MODULE_MUTEX_SUPPORTED
	mutex_unlock(&module_mutex);
#endif
	return 0;
}

static int __init cas_init_module(void)
{
	int result = 0;
	result = cas_casdisk_lookup_funtions();
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Could not find cas_disk functions.\n");
		return result;
	}

	if (casdisk_functions.casdsk_get_version() != CASDSK_IFACE_VERSION) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Incompatible cas_disk module\n");
		return -EINVAL;
	}

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

	result = cas_initialize_context();
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Cannot initialize cache library\n");
		return result;
	}

	result = cas_ctrl_device_init();
	if (result) {
		printk(KERN_ERR OCF_PREFIX_SHORT
				"Cannot initialize control device\n");
		goto error_cas_ctx_init;
	}

	printk(KERN_INFO "%s Version %s (%s)::Module loaded successfully\n",
		OCF_PREFIX_LONG, CAS_VERSION, CAS_KERNEL);

	return 0;

error_cas_ctx_init:
	cas_cleanup_context();

	return result;
}

module_init(cas_init_module);

static void __exit cas_exit_module(void)
{
	cas_ctrl_device_deinit();
	cas_cleanup_context();
}

module_exit(cas_exit_module);
