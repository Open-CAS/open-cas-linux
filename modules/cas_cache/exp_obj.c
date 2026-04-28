/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024-2025 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/module.h>
#include <linux/blkdev.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/blk-mq.h>
#include <linux/fs.h>
#include <linux/vmalloc.h>

#include "exp_obj.h"
#include "disk.h"
#include "debug.h"

#define CAS_DEV_MINORS 16
#define CAS_MINOR_SLOT_SIZE 256
#define CAS_MINOR_SLOT_MAX ((1 << MINORBITS) / CAS_MINOR_SLOT_SIZE - 1)
#define KMEM_CACHE_MIN_SIZE sizeof(void *)

struct cas_exp_obj_global {
	int disk_major;
	struct ida minor_ida;

	struct kmem_cache *kmem_cache;
} exp_obj_global;

static inline int bd_claim_by_disk(struct block_device *bdev, void *holder,
				   struct gendisk *disk)
{
	return bd_link_disk_holder(bdev, disk);
}

static inline void bd_release_from_disk(struct block_device *bdev,
					struct gendisk *disk)
{
	return bd_unlink_disk_holder(bdev, disk);
}

int __init cas_init_exp_objs(void)
{
	CAS_DEBUG_TRACE();

	exp_obj_global.disk_major = register_blkdev(
			exp_obj_global.disk_major, "cas");
	if (exp_obj_global.disk_major <= 0) {
		CAS_DEBUG_ERROR("Cannot allocate major number");
		return -EINVAL;
	}
	CAS_DEBUG_PARAM("Allocated major number: %d",
			exp_obj_global.disk_major);

	ida_init(&exp_obj_global.minor_ida);

	exp_obj_global.kmem_cache = kmem_cache_create("cas_exp_obj",
			sizeof(struct cas_exp_obj), 0, 0, NULL);
	if (!exp_obj_global.kmem_cache) {
		ida_destroy(&exp_obj_global.minor_ida);
		unregister_blkdev(exp_obj_global.disk_major, "cas");
		return -ENOMEM;
	}

	return 0;
}

void cas_deinit_exp_objs(void)
{
	CAS_DEBUG_TRACE();

	kmem_cache_destroy(exp_obj_global.kmem_cache);
	ida_destroy(&exp_obj_global.minor_ida);
	unregister_blkdev(exp_obj_global.disk_major, "cas");
}

static CAS_MAKE_REQ_RET_TYPE _cas_exp_obj_submit_bio(struct bio *bio)
{
	struct cas_exp_obj *exp_obj;

	BUG_ON(!bio);
	exp_obj = CAS_BIO_GET_GENDISK(bio)->private_data;

	exp_obj->ops->submit_bio(exp_obj, bio);

	CAS_KRETURN(0);
}

static CAS_MAKE_REQ_RET_TYPE _cas_exp_obj_make_rq_fn(struct request_queue *q,
						 struct bio *bio)
{
	_cas_exp_obj_submit_bio(bio);
	cas_blk_queue_exit(q);
	CAS_KRETURN(0);
}

static int _cas_exp_obj_allocate_minor_slot(void)
{
	return ida_alloc_max(&exp_obj_global.minor_ida,
			CAS_MINOR_SLOT_MAX, GFP_KERNEL);
}

static void _cas_exp_obj_free_minor_slot(int slot)
{
	ida_free(&exp_obj_global.minor_ida, slot);
}

static int _cas_exp_obj_set_dev_t(struct cas_exp_obj *exp_obj,
		struct gendisk *gd)
{
	struct cas_disk *dsk = exp_obj->dsk;
	struct block_device *bdev = cas_disk_get_blkdev(dsk);
	int minors = GET_DISK_MAX_PARTS(cas_disk_get_gendisk(dsk));
	int flags;

	if (cas_bdev_whole(bdev) != bdev) {
		minors = 1;
		flags = 0;
	} else {
		flags = cas_disk_get_gd_flags(dsk);
	}

	exp_obj->minor_slot = _cas_exp_obj_allocate_minor_slot();
	if (exp_obj->minor_slot < 0)
		return -ENOSPC;

	gd->first_minor = exp_obj->minor_slot * CAS_MINOR_SLOT_SIZE;
	gd->minors = minors;

	gd->major = exp_obj_global.disk_major;
	gd->flags |= flags;

	return 0;
}

static void _cas_exp_obj_clear_dev_t(struct cas_exp_obj *exp_obj)
{
	_cas_exp_obj_free_minor_slot(exp_obj->minor_slot);
}

CAS_BDEV_OPEN(_cas_exp_obj_open, struct gendisk *gd)
{
	struct cas_exp_obj *exp_obj = gd->private_data;
	int result = -ENAVAIL;

	mutex_lock(&exp_obj->openers_lock);

	if (!exp_obj->claimed) {
		if (unlikely(exp_obj->openers == UINT_MAX)) {
			result = -EBUSY;
		} else {
			exp_obj->openers++;
			result = 0;
		}
	}

	mutex_unlock(&exp_obj->openers_lock);
	return result;
}

CAS_BDEV_CLOSE(_cas_exp_obj_close, struct gendisk *gd)
{
	struct cas_exp_obj *exp_obj = gd->private_data;

	BUG_ON(exp_obj->openers == 0);

	mutex_lock(&exp_obj->openers_lock);
	exp_obj->openers--;
	mutex_unlock(&exp_obj->openers_lock);

}

static const struct block_device_operations _cas_exp_obj_ops = {
	.owner = THIS_MODULE,
	.open = CAS_REFER_BDEV_OPEN_CALLBACK(_cas_exp_obj_open),
	.release = CAS_REFER_BDEV_CLOSE_CALLBACK(_cas_exp_obj_close),
	CAS_SET_SUBMIT_BIO(_cas_exp_obj_submit_bio)
};

static struct cas_exp_obj *cas_exp_obj_alloc(void)
{
	struct cas_exp_obj *exp_obj;

	exp_obj = kmem_cache_zalloc(exp_obj_global.kmem_cache, GFP_KERNEL);
	if (!exp_obj) {
		CAS_DEBUG_ERROR("Cannot allocate memory");
		return NULL;
	}

	return exp_obj;
}

static void cas_exp_obj_free(struct cas_exp_obj *exp_obj)
{
	if (!exp_obj)
		return;

	kmem_cache_free(exp_obj_global.kmem_cache, exp_obj);
}

static CAS_BLK_STATUS_T _cas_exp_obj_queue_rq(struct blk_mq_hw_ctx *hctx,
		const struct blk_mq_queue_data *bd)
{
	return CAS_BLK_STS_NOTSUPP;
}

static struct blk_mq_ops cas_mq_ops = {
	.queue_rq       = _cas_exp_obj_queue_rq,
#ifdef CAS_BLK_MQ_OPS_MAP_QUEUE
	.map_queue	= blk_mq_map_queue,
#endif
};

static void _cas_init_queues(struct cas_exp_obj *exp_obj)
{
	struct request_queue *q = exp_obj->queue;
	struct blk_mq_hw_ctx *hctx;
	unsigned long i;

	queue_for_each_hw_ctx(q, hctx, i) {
		if (!hctx->nr_ctx || !hctx->tags)
			continue;

		hctx->driver_data = exp_obj;
	}
}

static int _cas_init_tag_set(struct cas_exp_obj *exp_obj)
{
	struct blk_mq_tag_set *set = &exp_obj->tag_set;

	set->ops = &cas_mq_ops;
	set->nr_hw_queues = num_online_cpus();
	set->numa_node = NUMA_NO_NODE;
	/*TODO: Should we inherit qd from core device? */
	set->queue_depth = CAS_BLKDEV_DEFAULT_RQ;

	set->cmd_size = 0;
	set->flags = CAS_BLK_MQ_F_SHOULD_MERGE | CAS_BLK_MQ_F_STACKING |
			CAS_BLK_MQ_F_BLOCKING;

	set->driver_data = exp_obj;

	return blk_mq_alloc_tag_set(set);
}

static int _cas_exp_obj_check_path(const char *dev_name)
{
	struct file *exported;
	char *path;
	int result;

	path = kmalloc(PATH_MAX, GFP_KERNEL);
	if (!path)
		return -ENOMEM;

	snprintf(path, PATH_MAX, "/dev/%s", dev_name);

	exported = filp_open(path, O_RDONLY, 0);

	if (!IS_ERR_OR_NULL(exported)) {
		filp_close(exported, NULL);
		result = -EEXIST;

	} else {
		/* failed to open file - it is safe to assume,
		 * it does not exist
		 */
		result = 0;
	}

	kfree(path);

	return result;
}

static ssize_t device_attr_serial_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	struct gendisk *gd = dev_to_disk(dev);
	struct cas_exp_obj *exp_obj = gd->private_data;

	return sysfs_emit(buf, "opencas-%s", exp_obj->dev_name);
}

static struct device_attribute device_attr_serial =
	__ATTR(serial, 0444, device_attr_serial_show, NULL);

static struct attribute *device_attrs[] = {
	&device_attr_serial.attr,
	NULL,
};

static const struct attribute_group device_attr_group = {
	.attrs = device_attrs,
	.name = "device",
};

struct cas_exp_obj *cas_exp_obj_create(struct cas_disk *dsk,
		const char *dev_name, struct module *owner,
		struct cas_exp_obj_ops *ops, void *priv)
{
	struct cas_exp_obj *exp_obj;
	struct request_queue *queue;
	struct gendisk *gd;
	cas_queue_limits_t queue_limits;
	int result = 0;

	BUG_ON(!owner);
	BUG_ON(!dsk);
	BUG_ON(!ops);

	if (strlen(dev_name) >= DISK_NAME_LEN)
		return ERR_PTR(-EINVAL);

	result = _cas_exp_obj_check_path(dev_name);
	if (result == -EEXIST) {
		printk(KERN_ERR "Could not activate exported object, "
				"because file /dev/%s exists.\n", dev_name);
	}

	if (result)
		return ERR_PTR(result);

	exp_obj = cas_exp_obj_alloc();
	if (!exp_obj)
		return ERR_PTR(-ENOMEM);

	cas_disk_get(dsk);
	exp_obj->dsk = dsk;

	result = cas_disk_hide_parts(dsk);
	if (result)
		goto error_hide_parts;

	mutex_init(&exp_obj->openers_lock);

	exp_obj->dev_name = kstrdup(dev_name, GFP_KERNEL);
	if (!exp_obj->dev_name) {
		result = -ENOMEM;
		goto error_kstrdup;
	}

	if (!try_module_get(owner)) {
		result = -ENAVAIL;
		goto error_module_get;
	}
	exp_obj->owner = owner;
	exp_obj->ops = ops;

	result = _cas_init_tag_set(exp_obj);
	if (result) {
		goto error_init_tag_set;
	}

	if (exp_obj->ops->set_queue_limits) {
		result = exp_obj->ops->set_queue_limits(exp_obj, &queue_limits);
		if (result)
			goto error_set_queue_limits;
	}

	result = cas_alloc_disk(&gd, &queue, &exp_obj->tag_set,
			&queue_limits);
	if (result) {
		goto error_alloc_mq_disk;
	}

	exp_obj->gd = gd;

	result = _cas_exp_obj_set_dev_t(exp_obj, gd);
	if (result)
		goto error_exp_obj_set_dev_t;

	BUG_ON(queue->queuedata);
	queue->queuedata = exp_obj;
	exp_obj->queue = queue;

	exp_obj->private = priv;

	_cas_init_queues(exp_obj);

	gd->fops = &_cas_exp_obj_ops;
	gd->private_data = exp_obj;
	strscpy(gd->disk_name, exp_obj->dev_name, sizeof(gd->disk_name));

	cas_blk_queue_make_request(queue, _cas_exp_obj_make_rq_fn);

	if (exp_obj->ops->set_geometry) {
		result = exp_obj->ops->set_geometry(exp_obj);
		if (result)
			goto error_set_geometry;
	}

	result = cas_add_disk(gd);
	if (result)
		goto error_add_disk;

	result = sysfs_create_group(&disk_to_dev(gd)->kobj, &device_attr_group);
	if (result)
		goto error_sysfs;

	result = bd_claim_by_disk(cas_disk_get_blkdev(dsk), exp_obj, gd);
	if (result)
		goto error_bd_claim;

	return exp_obj;


error_bd_claim:
	sysfs_remove_group(&disk_to_dev(gd)->kobj, &device_attr_group);
error_sysfs:
	del_gendisk(exp_obj->gd);
error_add_disk:
error_set_geometry:
	exp_obj->private = NULL;
	_cas_exp_obj_clear_dev_t(exp_obj);
error_exp_obj_set_dev_t:
	cas_cleanup_disk(gd);
	exp_obj->gd = NULL;
error_alloc_mq_disk:
error_set_queue_limits:
	blk_mq_free_tag_set(&exp_obj->tag_set);
error_init_tag_set:
	module_put(owner);
	exp_obj->owner = NULL;
error_module_get:
	kfree(exp_obj->dev_name);
error_kstrdup:
error_hide_parts:
	cas_disk_put(exp_obj->dsk);
	cas_exp_obj_free(exp_obj);
	return ERR_PTR(result);

}

int cas_exp_obj_dismantle(struct cas_exp_obj *exp_obj)
{
	BUG_ON(!exp_obj);

	bd_release_from_disk(cas_disk_get_blkdev(exp_obj->dsk), exp_obj->gd);
	_cas_exp_obj_clear_dev_t(exp_obj);
	del_gendisk(exp_obj->gd);

	if (exp_obj->queue)
		cas_cleanup_queue(exp_obj->queue);

	blk_mq_free_tag_set(&exp_obj->tag_set);

	put_disk(exp_obj->gd);

	return 0;
}

void cas_exp_obj_destroy(struct cas_exp_obj *exp_obj)
{
	struct module *owner;

	BUG_ON(!exp_obj);

	owner = exp_obj->owner;

	cas_disk_put(exp_obj->dsk);
	kfree(exp_obj->dev_name);
	cas_exp_obj_free(exp_obj);

	module_put(owner);
}

int cas_exp_obj_lock(struct cas_exp_obj *exp_obj)
{
	int result = -EBUSY;

	BUG_ON(!exp_obj);

	mutex_lock(&exp_obj->openers_lock);

	if (exp_obj->openers == 0) {
		exp_obj->claimed = true;
		result = 0;
	}

	mutex_unlock(&exp_obj->openers_lock);
	return result;
}

int cas_exp_obj_unlock(struct cas_exp_obj *exp_obj)
{
	BUG_ON(!exp_obj);

	mutex_lock(&exp_obj->openers_lock);
	exp_obj->claimed = false;
	mutex_unlock(&exp_obj->openers_lock);

	return 0;
}

void cas_exp_obj_set_priv(struct cas_exp_obj *exp_obj, void *priv)
{
	BUG_ON(!exp_obj);

	exp_obj->private = priv;
}

void *cas_exp_obj_get_priv(struct cas_exp_obj *exp_obj)
{
	BUG_ON(!exp_obj);

	return exp_obj->private;
}

struct request_queue *cas_exp_obj_get_queue(struct cas_exp_obj *exp_obj)
{
	BUG_ON(!exp_obj);

	return exp_obj->queue;
}

struct gendisk *cas_exp_obj_get_gendisk(struct cas_exp_obj *exp_obj)
{
	BUG_ON(!exp_obj);

	return exp_obj->gd;
}
