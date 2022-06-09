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
#include "sysfs.h"

#define CASDSK_DISK_OPEN_FMODE (FMODE_READ | FMODE_WRITE)

static const char * const _casdsk_disk_modes[] = {
	[CASDSK_MODE_UNKNOWN] = "unknown",
	[CASDSK_MODE_PT] = "pass-through",
	[CASDSK_MODE_ATTACHED] = "attached",
	[CASDSK_MODE_TRANS_TO_PT] = "attached -> pass-through",
	[CASDSK_MODE_TRANS_TO_ATTACHED] = "pass-through -> attached"
};

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

static ssize_t _casdsk_disk_mode_show(struct kobject *kobj, char *page)
{
	struct casdsk_disk *dsk = casdsk_kobj_to_disk(kobj);

	CASDSK_DEBUG_DISK_TRACE(dsk);

	return scnprintf(page, PAGE_SIZE, "%s",
			 _casdsk_disk_modes[atomic_read(&dsk->mode)]);
}

static struct casdsk_attribute _casdsk_disk_mode_attr =
	__ATTR(mode, S_IRUGO, _casdsk_disk_mode_show, NULL);

static struct attribute *_casdsk_disk_attrs[] = {
	&_casdsk_disk_mode_attr.attr,
	NULL
};

static struct kobj_type casdsk_disk_ktype = {
	.release = _casdsk_disk_release,
	.sysfs_ops = &casdsk_sysfs_ops,
	.default_attrs = _casdsk_disk_attrs
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

	atomic_set(&dsk->mode, CASDSK_MODE_UNKNOWN);

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

void __exit casdsk_disk_shutdown_all(void)
{
	struct list_head *item, *n;
	struct casdsk_disk *dsk;

	CASDSK_DEBUG_TRACE();

	mutex_lock(&casdsk_module->lock);

	list_for_each_safe(item, n, &casdsk_module->disk_list) {
		dsk = list_entry(item, struct casdsk_disk, list);

		list_del(item);

		casdsk_disk_lock(dsk);

		BUG_ON(!casdsk_disk_is_pt(dsk) && !casdsk_disk_is_unknown(dsk));

		if (casdsk_disk_is_pt(dsk)) {
			atomic_set(&dsk->mode, CASDSK_MODE_TRANS_TO_SHUTDOWN);
			casdsk_exp_obj_prepare_shutdown(dsk);
		}

		atomic_set(&dsk->mode, CASDSK_MODE_SHUTDOWN);

		if (dsk->exp_obj) {
			casdsk_exp_obj_lock(dsk);
			casdsk_exp_obj_destroy(dsk);
			casdsk_exp_obj_unlock(dsk);
		}

		casdsk_disk_unlock(dsk);
		__casdsk_disk_close(dsk);

	}

	mutex_unlock(&casdsk_module->lock);
}

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
EXPORT_SYMBOL(casdsk_disk_get_gendisk);

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

static inline int __casdsk_disk_set_pt(struct casdsk_disk *dsk)
{
	BUG_ON(!dsk);
	atomic_set(&dsk->mode, CASDSK_MODE_TRANS_TO_PT);
	casdsk_exp_obj_prepare_pt(dsk);
	return 0;
}

int casdsk_disk_set_pt(struct casdsk_disk *dsk)
{
	int result;

	CASDSK_DEBUG_DISK_TRACE(dsk);

	if (!dsk->exp_obj)
		return 0;

	casdsk_disk_lock(dsk);
	result = __casdsk_disk_set_pt(dsk);
	casdsk_disk_unlock(dsk);

	return result;
}
EXPORT_SYMBOL(casdsk_disk_set_pt);

static inline int __casdsk_disk_set_attached(struct casdsk_disk *dsk)
{
	atomic_set(&dsk->mode, CASDSK_MODE_TRANS_TO_ATTACHED);
	casdsk_exp_obj_prepare_attached(dsk);

	return 0;
}

int casdsk_disk_set_attached(struct casdsk_disk *dsk)
{
	int result;

	BUG_ON(!dsk);
	CASDSK_DEBUG_DISK_TRACE(dsk);

	if (!dsk->exp_obj)
		return 0;

	casdsk_disk_lock(dsk);
	result = __casdsk_disk_set_attached(dsk);
	casdsk_disk_unlock(dsk);

	return result;
}
EXPORT_SYMBOL(casdsk_disk_set_attached);

static inline int __casdsk_disk_clear_pt(struct casdsk_disk *dsk)
{
	BUG_ON(atomic_read(&dsk->mode) != CASDSK_MODE_TRANS_TO_PT);
	atomic_set(&dsk->mode, CASDSK_MODE_ATTACHED);
	return 0;
}

int casdsk_disk_clear_pt(struct casdsk_disk *dsk)
{
	int result;

	BUG_ON(!dsk);
	CASDSK_DEBUG_DISK_TRACE(dsk);

	if (!dsk->exp_obj)
		return 0;

	casdsk_disk_lock(dsk);
	result = __casdsk_disk_clear_pt(dsk);
	casdsk_disk_unlock(dsk);

	return result;
}
EXPORT_SYMBOL(casdsk_disk_clear_pt);

static inline int __casdsk_disk_detach(struct casdsk_disk *dsk)
{
	int result;

	BUG_ON(atomic_read(&dsk->mode) != CASDSK_MODE_TRANS_TO_PT);

	atomic_set(&dsk->mode, CASDSK_MODE_PT);

	result = casdsk_exp_obj_detach(dsk);
	if (result) {
		atomic_set(&dsk->mode, CASDSK_MODE_ATTACHED);
		return result;
	}

	return 0;
}

int casdsk_disk_detach(struct casdsk_disk *dsk)
{
	int result;

	BUG_ON(!dsk);
	CASDSK_DEBUG_DISK_TRACE(dsk);

	if (!dsk->exp_obj)
		return 0;

	casdsk_disk_lock(dsk);
	result = __casdsk_disk_detach(dsk);
	casdsk_disk_unlock(dsk);

	return result;

}
EXPORT_SYMBOL(casdsk_disk_detach);

static inline int __casdsk_disk_attach(struct casdsk_disk *dsk,
		struct module *owner, struct casdsk_exp_obj_ops *ops)
{
	int result;

	BUG_ON(!ops);
	BUG_ON(atomic_read(&dsk->mode) != CASDSK_MODE_TRANS_TO_ATTACHED);

	result = casdsk_exp_obj_attach(dsk, owner, ops);
	if (result) {
		atomic_set(&dsk->mode, CASDSK_MODE_PT);
		return result;
	}

	atomic_set(&dsk->mode, CASDSK_MODE_ATTACHED);

	return 0;
}

int casdsk_disk_attach(struct casdsk_disk *dsk, struct module *owner,
		     struct casdsk_exp_obj_ops *ops)
{
	int result;

	CASDSK_DEBUG_DISK_TRACE(dsk);

	if (!dsk->exp_obj)
		return 0;

	casdsk_disk_lock(dsk);
	result = __casdsk_disk_attach(dsk, owner, ops);
	casdsk_disk_unlock(dsk);

	return result;

}
EXPORT_SYMBOL(casdsk_disk_attach);
