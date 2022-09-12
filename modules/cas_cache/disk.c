/*
* Copyright(c) 2012-2022 Intel Corporation
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

#define CAS_DISK_OPEN_FMODE (FMODE_READ | FMODE_WRITE)

static inline struct cas_disk *cas_kobj_to_disk(struct kobject *kobj)
{
	return container_of(kobj, struct cas_disk, kobj);
}

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

static void _cas_disk_release(struct kobject *kobj)
{
	struct cas_disk *dsk;

	BUG_ON(!kobj);

	dsk = cas_kobj_to_disk(kobj);
	BUG_ON(!dsk);

	CAS_DEBUG_DISK_TRACE(dsk);

	kfree(dsk->path);

	kmem_cache_free(cas_module.disk_cache, dsk);
}

static struct kobj_type cas_disk_ktype = {
	.release = _cas_disk_release,
};

int __init cas_init_disks(void)
{
	CAS_DEBUG_TRACE();

	cas_module.next_disk_id = 1;
	INIT_LIST_HEAD(&cas_module.disk_list);

	cas_module.disk_major = register_blkdev(cas_module.disk_major,
						  "cas");
	if (cas_module.disk_major <= 0) {
		CAS_DEBUG_ERROR("Cannot allocate major number");
		return -EINVAL;
	}
	CAS_DEBUG_PARAM("Allocated major number: %d", cas_module.disk_major);

	cas_module.disk_cache =
		kmem_cache_create("cas_disk", sizeof(struct cas_disk),
				  0, 0, NULL);
	if (!cas_module.disk_cache) {
		unregister_blkdev(cas_module.disk_major, "cas");
		return -ENOMEM;
	}

	return 0;
}

void cas_deinit_disks(void)
{
	CAS_DEBUG_TRACE();

	kmem_cache_destroy(cas_module.disk_cache);
	unregister_blkdev(cas_module.disk_major, "cas");
}

static int _cas_disk_init_kobject(struct cas_disk *dsk)
{
	int result = 0;

	kobject_init(&dsk->kobj, &cas_disk_ktype);
	result = kobject_add(&dsk->kobj, &disk_to_dev(dsk->bd->bd_disk)->kobj,
			     "cas%d", dsk->id);
	if (result)
		CAS_DEBUG_DISK_ERROR(dsk, "Cannot register kobject");

	return result;
}

struct cas_disk *cas_disk_open(const char *path, void *private)
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

	mutex_init(&dsk->openers_lock);

	dsk->path = kstrdup(path, GFP_KERNEL);
	if (!dsk->path) {
		result = -ENOMEM;
		goto error_kstrdup;
	}

	dsk->bd = open_bdev_exclusive(path, CAS_DISK_OPEN_FMODE, dsk);
	if (IS_ERR(dsk->bd)) {
		CAS_DEBUG_ERROR("Cannot open exclusive");
		result = PTR_ERR(dsk->bd);
		goto error_open_bdev;
	}

	dsk->private = private;

	dsk->id = cas_module.next_disk_id++;
	list_add(&dsk->list, &cas_module.disk_list);

	result = _cas_disk_init_kobject(dsk);
	if (result)
		goto error_kobject;

	CAS_DEBUG_DISK(dsk, "Created (%p)", dsk);

	return dsk;

error_kobject:
	list_del(&dsk->list);
	close_bdev_exclusive(dsk->bd, CAS_DISK_OPEN_FMODE);
error_open_bdev:
	kfree(dsk->path);
error_kstrdup:
	kmem_cache_free(cas_module.disk_cache, dsk);
error_kmem:
	return ERR_PTR(result);
}

static void _cas_disk_claim(struct cas_disk *dsk, void *private)
{
	dsk->private = private;
}

struct cas_disk *cas_disk_claim(const char *path, void *private)
{
	struct list_head *item;
	struct cas_disk *dsk = NULL;

	BUG_ON(!path);

	list_for_each(item, &cas_module.disk_list) {
		dsk = list_entry(item, struct cas_disk, list);
		if (strncmp(path, dsk->path, PATH_MAX) == 0) {
			_cas_disk_claim(dsk, private);
			return dsk;
		}
	}
	return NULL;
}

static void __cas_disk_close(struct cas_disk *dsk)
{
	close_bdev_exclusive(dsk->bd, CAS_DISK_OPEN_FMODE);

	cas_exp_obj_free(dsk);
	kobject_put(&dsk->kobj);
}

void cas_disk_close(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);

	CAS_DEBUG_DISK(dsk, "Destroying (%p)", dsk);

	list_del(&dsk->list);

	__cas_disk_close(dsk);
}

struct block_device *cas_disk_get_blkdev(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	return dsk->bd;
}

struct gendisk *cas_disk_get_gendisk(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);
	return dsk->bd->bd_disk;
}

struct request_queue *cas_disk_get_queue(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->bd);
	return cas_bdev_whole(dsk->bd)->bd_disk->queue;
}

int cas_disk_allocate_minors(int count)
{
	int minor = -1;

	if (cas_module.next_minor + count <= (1 << MINORBITS)) {
		minor = cas_module.next_minor;
		cas_module.next_minor += count;
	}

	return minor;
}
