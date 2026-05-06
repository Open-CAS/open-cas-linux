/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __CAS_BD_DISK_PRIV_H__
#define __CAS_BD_DISK_PRIV_H__

#include <linux/idr.h>
#include "generated_defines.h"
#include "disk.h"

struct cas_disk {
	struct list_head list;

	char *path;
	cas_bdev_handle_t bdev_handle;

	int refcount;
	bool hidden;

	int gd_flags;
	int gd_minors;
};

int __init cas_init_disks(void);

void cas_deinit_disks(void);

int cas_disk_get_gd_flags(struct cas_disk *dsk);

int cas_disk_hide_parts(struct cas_disk *dsk);

#endif
