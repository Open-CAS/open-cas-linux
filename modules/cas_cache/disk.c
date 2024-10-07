/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/fs.h>
#include <linux/delay.h>
#include "cas_cache.h"
#include "disk.h"
#include "exp_obj.h"
#include "debug.h"

#define CAS_DISK_OPEN_MODE (CAS_BLK_MODE_READ | CAS_BLK_MODE_WRITE)

static inline cas_bdev_handle_t open_bdev_exclusive(const char *path,
		CAS_BLK_MODE mode, void *holder)
{
	return cas_bdev_open_by_path(path, mode | CAS_BLK_MODE_EXCL, holder);
}

static inline void close_bdev_exclusive(cas_bdev_handle_t handle,
		CAS_BLK_MODE mode, void *holder)
{
	cas_bdev_release(handle, mode | CAS_BLK_MODE_EXCL, holder);
}

int __init cas_init_disks(void)
{
	CAS_DEBUG_TRACE();

	cas_module.disk_cache =
		kmem_cache_create("cas_disk", sizeof(struct cas_disk),
				  0, 0, NULL);
	if (!cas_module.disk_cache)
		return -ENOMEM;

	return 0;
}

void cas_deinit_disks(void)
{
	CAS_DEBUG_TRACE();

	kmem_cache_destroy(cas_module.disk_cache);
}

struct cas_disk *cas_disk_open(const char *path)
{
	struct cas_disk *dsk;
	int result = 0;

	BUG_ON(!path);

	CAS_DEBUG_TRACE();

	dsk = kmem_cache_zalloc(cas_module.disk_cache, GFP_KERNEL);
	if (!dsk) {
		CAS_DEBUG_ERROR("Cannot allocate memory");
		result = -ENOMEM;
		goto error_kmem;
	}

	dsk->path = kstrdup(path, GFP_KERNEL);
	if (!dsk->path) {
		result = -ENOMEM;
		goto error_kstrdup;
	}

	dsk->bdev_handle = open_bdev_exclusive(path, CAS_DISK_OPEN_MODE, dsk);
	if (IS_ERR(dsk->bdev_handle)) {
		CAS_DEBUG_ERROR("Cannot open exclusive");
		result = PTR_ERR(dsk->bdev_handle);
		goto error_open_bdev;
	}

	CAS_DEBUG_DISK(dsk, "Created (%p)", dsk);

	return dsk;

error_open_bdev:
	kfree(dsk->path);
error_kstrdup:
	kmem_cache_free(cas_module.disk_cache, dsk);
error_kmem:
	return ERR_PTR(result);
}

void cas_disk_close(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bdev_handle);

	CAS_DEBUG_DISK(dsk, "Destroying (%p)", dsk);

	close_bdev_exclusive(dsk->bdev_handle, CAS_DISK_OPEN_MODE, dsk);

	kfree(dsk->path);
	kmem_cache_free(cas_module.disk_cache, dsk);
}

struct block_device *cas_disk_get_blkdev(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bdev_handle);
	return cas_bdev_get_from_handle(dsk->bdev_handle);
}

struct gendisk *cas_disk_get_gendisk(struct cas_disk *dsk)
{
	return cas_disk_get_blkdev(dsk)->bd_disk;
}

struct request_queue *cas_disk_get_queue(struct cas_disk *dsk)
{
	struct block_device *bd = cas_disk_get_blkdev(dsk);

	return cas_bdev_whole(bd)->bd_disk->queue;
}
