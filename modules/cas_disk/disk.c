/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/fs.h>
#include <linux/delay.h>
#include "cas_disk_defs.h"
#include "cas_cache.h"
#include "disk.h"
#include "exp_obj.h"

#define CASDSK_DISK_OPEN_FMODE (FMODE_READ | FMODE_WRITE)

static inline struct block_device *open_bdev_exclusive(const char *path,
						       fmode_t mode,
						       void *holder)
{
	return blkdev_get_by_path(path, mode | FMODE_EXCL, holder);
}

static inline void close_bdev_exclusive(struct block_device *bdev, fmode_t mode)
{
	blkdev_put(bdev, mode | FMODE_EXCL);
}

static void _casdsk_disk_release(struct kobject *kobj)
{
	struct casdsk_disk *dsk;

	BUG_ON(!kobj);

	dsk = casdsk_kobj_to_disk(kobj);
	BUG_ON(!dsk);

	CASDSK_DEBUG_DISK_TRACE(dsk);

	kfree(dsk->path);

	kmem_cache_free(casdsk_module->disk_cache, dsk);
}

static struct kobj_type casdsk_disk_ktype = {
	.release = _casdsk_disk_release,
};

int __init casdsk_init_disks(void)
{
	CASDSK_DEBUG_TRACE();

	casdsk_module->next_disk_id = 1;
	INIT_LIST_HEAD(&casdsk_module->disk_list);

	casdsk_module->disk_major = register_blkdev(casdsk_module->disk_major,
						  "cas");
	if (casdsk_module->disk_major <= 0) {
		CASDSK_DEBUG_ERROR("Cannot allocate major number");
		return -EINVAL;
	}
	CASDSK_DEBUG_PARAM("Allocated major number: %d", casdsk_module->disk_major);

	casdsk_module->disk_cache =
		kmem_cache_create("casdsk_disk", sizeof(struct casdsk_disk),
				  0, 0, NULL);
	if (!casdsk_module->disk_cache) {
		unregister_blkdev(casdsk_module->disk_major, "cas");
		return -ENOMEM;
	}

	return 0;
}

void casdsk_deinit_disks(void)
{
	CASDSK_DEBUG_TRACE();

	kmem_cache_destroy(casdsk_module->disk_cache);
	unregister_blkdev(casdsk_module->disk_major, "cas");
}

static int _casdsk_disk_init_kobject(struct casdsk_disk *dsk)
{
	int result = 0;

	kobject_init(&dsk->kobj, &casdsk_disk_ktype);
	result = kobject_add(&dsk->kobj, &disk_to_dev(dsk->bd->bd_disk)->kobj,
			     "cas%d", dsk->id);
	if (result)
		CASDSK_DEBUG_DISK_ERROR(dsk, "Cannot register kobject");

	return result;
}

struct casdsk_disk *casdsk_disk_open(const char *path, void *private)
{
	struct casdsk_disk *dsk;
	int result = 0;

	BUG_ON(!path);

	CASDSK_DEBUG_TRACE();

	dsk = kmem_cache_zalloc(casdsk_module->disk_cache, GFP_KERNEL);
	if (!dsk) {
		CASDSK_DEBUG_ERROR("Cannot allocate memory");
		result = -ENOMEM;
		goto error_kmem;
	}
	mutex_init(&dsk->lock);

	mutex_init(&dsk->openers_lock);

	dsk->path = kstrdup(path, GFP_KERNEL);
	if (!dsk->path) {
		result = -ENOMEM;
		goto error_kstrdup;
	}

	dsk->bd = open_bdev_exclusive(path, CASDSK_DISK_OPEN_FMODE, dsk);
	if (IS_ERR(dsk->bd)) {
		CASDSK_DEBUG_ERROR("Cannot open exclusive");
		result = PTR_ERR(dsk->bd);
		goto error_open_bdev;
	}

	dsk->private = private;

	mutex_lock(&casdsk_module->lock);

	dsk->id = casdsk_module->next_disk_id++;
	list_add(&dsk->list, &casdsk_module->disk_list);

	mutex_unlock(&casdsk_module->lock);

	result = _casdsk_disk_init_kobject(dsk);
	if (result)
		goto error_kobject;

	CASDSK_DEBUG_DISK(dsk, "Created (%p)", dsk);

	return dsk;

error_kobject:
	mutex_lock(&casdsk_module->lock);
	list_del(&dsk->list);
	mutex_unlock(&casdsk_module->lock);
	close_bdev_exclusive(dsk->bd, CASDSK_DISK_OPEN_FMODE);
error_open_bdev:
	kfree(dsk->path);
error_kstrdup:
	kmem_cache_free(casdsk_module->disk_cache, dsk);
error_kmem:
	return ERR_PTR(result);
}
EXPORT_SYMBOL(casdsk_disk_open);

static void _casdsk_disk_claim(struct casdsk_disk *dsk, void *private)
{
	dsk->private = private;
}

struct casdsk_disk *casdsk_disk_claim(const char *path, void *private)
{
	struct list_head *item;
	struct casdsk_disk *dsk = NULL;

	BUG_ON(!path);

	mutex_lock(&casdsk_module->lock);
	list_for_each(item, &casdsk_module->disk_list) {
		dsk = list_entry(item, struct casdsk_disk, list);
		if (strncmp(path, dsk->path, PATH_MAX) == 0) {
			_casdsk_disk_claim(dsk, private);
			mutex_unlock(&casdsk_module->lock);
			return dsk;
		}
	}
	mutex_unlock(&casdsk_module->lock);
	return NULL;
}
EXPORT_SYMBOL(casdsk_disk_claim);

static void __casdsk_disk_close(struct casdsk_disk *dsk)
{
	close_bdev_exclusive(dsk->bd, CASDSK_DISK_OPEN_FMODE);

	casdsk_exp_obj_free(dsk);
	kobject_put(&dsk->kobj);
}

void casdsk_disk_close(struct casdsk_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);

	CASDSK_DEBUG_DISK(dsk, "Destroying (%p)", dsk);

	mutex_lock(&casdsk_module->lock);

	list_del(&dsk->list);

	mutex_unlock(&casdsk_module->lock);

	__casdsk_disk_close(dsk);
}
EXPORT_SYMBOL(casdsk_disk_close);

struct block_device *casdsk_disk_get_blkdev(struct casdsk_disk *dsk)
{
	BUG_ON(!dsk);
	return dsk->bd;
}
EXPORT_SYMBOL(casdsk_disk_get_blkdev);

struct gendisk *casdsk_disk_get_gendisk(struct casdsk_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);
	return dsk->bd->bd_disk;
}

struct request_queue *casdsk_disk_get_queue(struct casdsk_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);
	return cas_bdev_whole(dsk->bd)->bd_disk->queue;
}
EXPORT_SYMBOL(casdsk_disk_get_queue);

int casdsk_disk_allocate_minors(int count)
{
	int minor = -1;

	mutex_lock(&casdsk_module->lock);
	if (casdsk_module->next_minor + count <= (1 << MINORBITS)) {
		minor = casdsk_module->next_minor;
		casdsk_module->next_minor += count;
	}
	mutex_unlock(&casdsk_module->lock);

	return minor;
}
