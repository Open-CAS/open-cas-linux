/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __CAS_CACHE_H__
#define __CAS_CACHE_H__

#include "ocf/ocf.h"
#include "ocf_env.h"

#include <cas_version.h>
#include <cas_ioctl_codes.h>

#include "linux_kernel_version.h"
#include "layer_upgrade.h"
#include "control.h"
#include "layer_cache_management.h"
#include "service_ui_ioctl.h"
#include "utils/cas_cache_utils.h"
#include "volume/vol_blk_utils.h"
#include "classifier.h"
#include "context.h"
#include <linux/kallsyms.h>

#define CAS_KERN_EMERG KERN_EMERG OCF_PREFIX_SHORT
#define CAS_KERN_ALERT KERN_ALERT OCF_PREFIX_SHORT
#define CAS_KERN_CRIT KERN_CRIT OCF_PREFIX_SHORT
#define CAS_KERN_ERR KERN_ERR OCF_PREFIX_SHORT
#define CAS_KERN_WARNING KERN_WARNING OCF_PREFIX_SHORT
#define CAS_KERN_NOTICE KERN_NOTICE OCF_PREFIX_SHORT
#define CAS_KERN_INFO KERN_INFO OCF_PREFIX_SHORT
#define CAS_KERN_DEBUG KERN_DEBUG OCF_PREFIX_SHORT

#ifndef SECTOR_SHIFT
#define SECTOR_SHIFT 9
#endif

#ifndef SECTOR_SIZE
#define SECTOR_SIZE (1<<SECTOR_SHIFT)
#endif

#define MAX_LINES_PER_IO	16

/**
 * cache/core object types */
enum {
	BLOCK_DEVICE_VOLUME = 1,	/**< block device volume */
	ATOMIC_DEVICE_VOLUME,		/**< block device volume with atomic
					     metadata support */
/** \cond SKIP_IN_DOC */
	OBJECT_TYPE_MAX,
	NVME_CONTROLLER
/** \endcond */
};

struct cas_classifier;

struct cache_priv {
	struct cas_classifier *classifier;
	atomic_t flush_interrupt_enabled;
	ocf_queue_t mngt_queue;
	ocf_queue_t io_queues[];
};

extern ocf_ctx_t cas_ctx;

extern struct casdsk_functions_mapper casdisk_functions;

struct casdsk_functions_mapper {
	int (*casdsk_disk_dettach)(struct casdsk_disk *dsk);
	int (*casdsk_exp_obj_destroy)(struct casdsk_disk *dsk);
	int (*casdsk_exp_obj_create)(struct casdsk_disk *dsk, const char *dev_name,
		struct module *owner, struct casdsk_exp_obj_ops *ops);
	void(*casdsk_exp_obj_free)(struct casdsk_disk *dsk);
	struct request_queue *(*casdsk_disk_get_queue)(struct casdsk_disk *dsk);
	void (*casdsk_store_config)(size_t n_blobs, struct casdsk_props_conf *blobs);
	struct block_device *(*casdsk_disk_get_blkdev)(struct casdsk_disk *dsk);
	struct request_queue *(*casdsk_exp_obj_get_queue)(struct casdsk_disk *dsk);
	uint32_t (*casdsk_get_version)(void);
	void (*casdsk_disk_close)(struct casdsk_disk *dsk);
	struct casdsk_disk *(*casdsk_disk_claim)(const char *path, void *private);
	int (*casdsk_exp_obj_unlock)(struct casdsk_disk *dsk);
	int (*casdsk_disk_set_pt)(struct casdsk_disk *dsk);
	size_t (*casdsk_get_stored_config)(struct casdsk_props_conf **blobs);
	struct gendisk *(*casdsk_disk_get_gendisk)(struct casdsk_disk *dsk);
	int (*casdsk_disk_attach) (struct casdsk_disk *dsk, struct module *owner,
		struct casdsk_exp_obj_ops *ops);
	int (*casdsk_disk_set_attached)(struct casdsk_disk *dsk);
	int (*casdsk_exp_obj_activate)(struct casdsk_disk *dsk);
	bool (*casdsk_exp_obj_activated)(struct casdsk_disk *ds);
	int (*casdsk_exp_obj_lock)(struct casdsk_disk *dsk);
	void (*casdsk_free_stored_config)(void);
	struct casdsk_disk *(*casdsk_disk_open)(const char *path, void *private);
	int (*casdsk_disk_clear_pt)(struct casdsk_disk *dsk);
	struct gendisk *(*casdsk_exp_obj_get_gendisk)(struct casdsk_disk *dsk);
};

#endif
