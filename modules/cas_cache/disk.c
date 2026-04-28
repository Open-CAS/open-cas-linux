/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/blkdev.h>
#include <linux/fs.h>
#include <linux/delay.h>
#include <linux/blkpg.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>
#include <linux/blk-mq.h>
#include "disk.h"
#include "debug.h"

#define CAS_DISK_OPEN_MODE (CAS_BLK_MODE_READ | CAS_BLK_MODE_WRITE)

struct cas_disk_global {
	struct list_head disks;
	struct kmem_cache *kmem_cache;
	struct mutex lock;
} disk_global;

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

	INIT_LIST_HEAD(&disk_global.disks);
	mutex_init(&disk_global.lock);

	disk_global.kmem_cache =
		kmem_cache_create("cas_disk", sizeof(struct cas_disk),
				  0, 0, NULL);
	if (!disk_global.kmem_cache)
		return -ENOMEM;

	return 0;
}

void cas_deinit_disks(void)
{
	CAS_DEBUG_TRACE();

	kmem_cache_destroy(disk_global.kmem_cache);
}

static int _cas_del_partitions(struct cas_disk *dsk)
{
	struct block_device *bd = cas_disk_get_blkdev(dsk);
	struct file *bd_file;
	unsigned long __user usr_bpart;
	unsigned long __user usr_barg;
	struct blkpg_partition bpart;
	struct blkpg_ioctl_arg barg;
	int result = 0;
	int part_no;

	bd_file = filp_open(dsk->path, 0, 0);
	if (IS_ERR(bd_file))
		return PTR_ERR(bd_file);

	usr_bpart = cas_vm_mmap(NULL, 0, sizeof(bpart));
	if (IS_ERR((void *)usr_bpart)) {
		result = PTR_ERR((void *)usr_bpart);
		goto out_map_bpart;
	}

	usr_barg = cas_vm_mmap(NULL, 0, sizeof(barg));
	if (IS_ERR((void *)usr_barg)) {
		result = PTR_ERR((void *)usr_barg);
		goto out_map_barg;
	}


	memset(&bpart, 0, sizeof(bpart));
	memset(&barg, 0, sizeof(barg));
	barg.data = (void __user *)usr_bpart;
	barg.op = BLKPG_DEL_PARTITION;

	result = copy_to_user((void __user *)usr_barg, &barg, sizeof(barg));
	if (result) {
		result = -EINVAL;
		goto out_copy;
	}

	while ((part_no = cas_bd_get_next_part(bd))) {
		bpart.pno = part_no;
		result = copy_to_user((void __user *)usr_bpart, &bpart,
				sizeof(bpart));
		if (result) {
			result = -EINVAL;
			break;
		}
		result = cas_vfs_ioctl(bd_file, BLKPG, usr_barg);
		if (result == 0) {
			printk(KERN_INFO "Partition %d on %s hidden\n",
				part_no, bd->bd_disk->disk_name);
		} else {
			printk(KERN_ERR
				"Error(%d) hiding the partition %d on %s\n",
				result, part_no, bd->bd_disk->disk_name);
			break;
		}
	}

out_copy:
	cas_vm_munmap(usr_barg, sizeof(barg));
out_map_barg:
	cas_vm_munmap(usr_bpart, sizeof(bpart));
out_map_bpart:
	filp_close(bd_file, NULL);
	return result;
}

int cas_disk_hide_parts(struct cas_disk *dsk)
{
	struct block_device *bd = cas_disk_get_blkdev(dsk);
	struct gendisk *gdsk = cas_disk_get_gendisk(dsk);

	if (bd != cas_bdev_whole(bd))
		/* It is partition, no more job required */
		return 0;

	if (dsk->hidden)
		return 0;

	if (GET_DISK_MAX_PARTS(cas_disk_get_gendisk(dsk)) > 1) {
		if (_cas_del_partitions(dsk)) {
			printk(KERN_ERR
				"Error deleting a partition on the device %s\n",
				gdsk->disk_name);

			/* Try restore previous partitions by rescaning */
			cas_reread_partitions(bd);
			return -EINVAL;
		}
	}

	/* Save original flags and minors */
	dsk->gd_flags = gdsk->flags & _CAS_GENHD_FLAGS;
	dsk->gd_minors = gdsk->minors;

	/* Setup disk of bottom device as not partitioned device */
	gdsk->flags &= ~_CAS_GENHD_FLAGS;
	gdsk->minors = 1;
	/* Rescan partitions */
	cas_reread_partitions(bd);

	dsk->hidden = true;

	return 0;
}

static void cas_disk_restore_parts(struct cas_disk *dsk)
{
	struct block_device *bdev = cas_disk_get_blkdev(dsk);
	struct gendisk *gdsk = cas_disk_get_gendisk(dsk);

	if (!dsk->hidden)
		return;

	if (cas_bdev_whole(bdev) == bdev) {
		gdsk->minors = dsk->gd_minors;
		gdsk->flags |= dsk->gd_flags;
		cas_reread_partitions(bdev);
	}

	dsk->hidden = false;
}

static struct cas_disk *cas_disk_lookup(const char *path)
{
	struct cas_disk *dsk;

	list_for_each_entry(dsk, &disk_global.disks, list) {
		if (!strcmp(dsk->path, path))
			return dsk;
	}

	return NULL;
}

struct cas_disk *cas_disk_open(const char *path)
{
	struct cas_disk *dsk;
	int result = 0;

	BUG_ON(!path);

	CAS_DEBUG_TRACE();

	mutex_lock(&disk_global.lock);
	dsk = cas_disk_lookup(path);
	if (dsk) {
		dsk->refcount++;
		mutex_unlock(&disk_global.lock);
		return dsk;
	}
	mutex_unlock(&disk_global.lock);

	dsk = kmem_cache_zalloc(disk_global.kmem_cache, GFP_KERNEL);
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

	dsk->refcount = 1;

	mutex_lock(&disk_global.lock);
	list_add_tail(&dsk->list, &disk_global.disks);
	mutex_unlock(&disk_global.lock);

	CAS_DEBUG_DISK(dsk, "Created (%p)", dsk);

	return dsk;

error_open_bdev:
	kfree(dsk->path);
error_kstrdup:
	kmem_cache_free(disk_global.kmem_cache, dsk);
error_kmem:
	return ERR_PTR(result);
}

void cas_disk_get(struct cas_disk *dsk)
{
	BUG_ON(!dsk);

	mutex_lock(&disk_global.lock);
	BUG_ON(dsk->refcount <= 0);
	dsk->refcount++;
	mutex_unlock(&disk_global.lock);
}

void cas_disk_put(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bdev_handle);

	mutex_lock(&disk_global.lock);
	BUG_ON(dsk->refcount <= 0);
	if (--dsk->refcount > 0) {
		mutex_unlock(&disk_global.lock);
		return;
	}
	list_del(&dsk->list);
	mutex_unlock(&disk_global.lock);

	CAS_DEBUG_DISK(dsk, "Destroying (%p)", dsk);

	cas_disk_restore_parts(dsk);

	close_bdev_exclusive(dsk->bdev_handle, CAS_DISK_OPEN_MODE, dsk);

	kfree(dsk->path);
	kmem_cache_free(disk_global.kmem_cache, dsk);
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

int cas_disk_get_gd_flags(struct cas_disk *dsk)
{
	return dsk->gd_flags;
}
