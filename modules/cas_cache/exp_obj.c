/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024-2025 Huawei Technologies
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/module.h>
#include <linux/blkdev.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/blkpg.h>
#include <linux/blk-mq.h>

#include "disk.h"
#include "exp_obj.h"
#include "linux_kernel_version.h"
#include "cas_cache.h"
#include "debug.h"

#define CAS_DEV_MINORS 16
#define KMEM_CACHE_MIN_SIZE sizeof(void *)

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

	cas_module.disk_major = register_blkdev(cas_module.disk_major,
			"cas");
	if (cas_module.disk_major <= 0) {
		CAS_DEBUG_ERROR("Cannot allocate major number");
		return -EINVAL;
	}
	CAS_DEBUG_PARAM("Allocated major number: %d", cas_module.disk_major);

	cas_module.exp_obj_cache = kmem_cache_create("cas_exp_obj",
			sizeof(struct cas_exp_obj), 0, 0, NULL);
	if (!cas_module.exp_obj_cache) {
		unregister_blkdev(cas_module.disk_major, "cas");
		return -ENOMEM;
	}

	return 0;
}

void cas_deinit_exp_objs(void)
{
	CAS_DEBUG_TRACE();

	kmem_cache_destroy(cas_module.exp_obj_cache);
	unregister_blkdev(cas_module.disk_major, "cas");
}

static CAS_MAKE_REQ_RET_TYPE _cas_exp_obj_submit_bio(struct bio *bio)
{
	struct cas_disk *dsk;
	struct cas_exp_obj *exp_obj;

	BUG_ON(!bio);
	dsk = CAS_BIO_GET_GENDISK(bio)->private_data;
	exp_obj = dsk->exp_obj;

	exp_obj->ops->submit_bio(dsk, bio, exp_obj->private);

	CAS_KRETURN(0);
}

static CAS_MAKE_REQ_RET_TYPE _cas_exp_obj_make_rq_fn(struct request_queue *q,
						 struct bio *bio)
{
	_cas_exp_obj_submit_bio(bio);
	cas_blk_queue_exit(q);
	CAS_KRETURN(0);
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
			printk(KERN_ERR "Error(%d) hiding the partition %d on %s\n",
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

static int _cas_exp_obj_hide_parts(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj = dsk->exp_obj;
	struct block_device *bd = cas_disk_get_blkdev(dsk);
	struct gendisk *gdsk = cas_disk_get_gendisk(dsk);

	if (bd != cas_bdev_whole(bd))
		/* It is partition, no more job required */
		return 0;

	if (GET_DISK_MAX_PARTS(cas_disk_get_gendisk(dsk)) > 1) {
		if (_cas_del_partitions(dsk)) {
			printk(KERN_ERR "Error deleting a partition on thedevice %s\n",
				gdsk->disk_name);

			/* Try restore previous partitions by rescaning */
			cas_reread_partitions(bd);
			return -EINVAL;
		}
	}

	/* Save original flags and minors */
	exp_obj->gd_flags = gdsk->flags & _CAS_GENHD_FLAGS;
	exp_obj->gd_minors = gdsk->minors;

	/* Setup disk of bottom device as not partitioned device */
	gdsk->flags &= ~_CAS_GENHD_FLAGS;
	gdsk->minors = 1;
	/* Rescan partitions */
	cas_reread_partitions(bd);

	return 0;
}

static int _cas_exp_obj_allocate_minors(int count)
{
	int minor = -1;

	if (cas_module.next_minor + count <= (1 << MINORBITS)) {
		minor = cas_module.next_minor;
		cas_module.next_minor += count;
	}

	return minor;
}

static int _cas_exp_obj_set_dev_t(struct cas_disk *dsk, struct gendisk *gd)
{
	struct cas_exp_obj *exp_obj = dsk->exp_obj;
	int flags;
	int minors = GET_DISK_MAX_PARTS(cas_disk_get_gendisk(dsk));
	struct block_device *bdev;

	bdev = cas_disk_get_blkdev(dsk);
	BUG_ON(!bdev);

	if (cas_bdev_whole(bdev) != bdev) {
		minors = 1;
		flags = 0;
	} else {
		if (_cas_exp_obj_hide_parts(dsk))
			return -EINVAL;
		flags = exp_obj->gd_flags;
	}

	gd->first_minor = _cas_exp_obj_allocate_minors(minors);
	if (gd->first_minor < 0) {
		CAS_DEBUG_DISK_ERROR(dsk, "Cannot allocate %d minors", minors);
		return -EINVAL;
	}
	gd->minors = minors;

	gd->major = cas_module.disk_major;
	gd->flags |= flags;

	return 0;
}

static void _cas_exp_obj_clear_dev_t(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj = dsk->exp_obj;
	struct block_device *bdev = cas_disk_get_blkdev(dsk);
	struct gendisk *gdsk = cas_disk_get_gendisk(dsk);

	if (cas_bdev_whole(bdev) == bdev) {
		/* Restore previous configuration of bottom disk */
		gdsk->minors = exp_obj->gd_minors;
		gdsk->flags |= exp_obj->gd_flags;
		cas_reread_partitions(bdev);
	}
}

CAS_BDEV_OPEN(_cas_exp_obj_open, struct gendisk *gd)
{
	struct cas_disk *dsk = gd->private_data;
	struct cas_exp_obj *exp_obj = dsk->exp_obj;
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

	mutex_unlock(&dsk->exp_obj->openers_lock);
	return result;
}

CAS_BDEV_CLOSE(_cas_exp_obj_close, struct gendisk *gd)
{
	struct cas_disk *dsk = gd->private_data;
	struct cas_exp_obj *exp_obj = dsk->exp_obj;

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

static int cas_exp_obj_alloc(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj;

	BUG_ON(!dsk);
	BUG_ON(dsk->exp_obj);

	CAS_DEBUG_DISK_TRACE(dsk);

	exp_obj = kmem_cache_zalloc(cas_module.exp_obj_cache, GFP_KERNEL);
	if (!exp_obj) {
		CAS_DEBUG_ERROR("Cannot allocate memory");
		return -ENOMEM;
	}

	dsk->exp_obj = exp_obj;

	return 0;
}

static void cas_exp_obj_free(struct cas_disk *dsk)
{
	if (!dsk->exp_obj)
		return;

	kmem_cache_free(cas_module.exp_obj_cache, dsk->exp_obj);
	dsk->exp_obj = NULL;
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

static void _cas_init_queues(struct cas_disk *dsk)
{
	struct request_queue *q = dsk->exp_obj->queue;
	struct blk_mq_hw_ctx *hctx;
	unsigned long i;

	queue_for_each_hw_ctx(q, hctx, i) {
		if (!hctx->nr_ctx || !hctx->tags)
			continue;

		hctx->driver_data = dsk;
	}
}

static int _cas_init_tag_set(struct cas_disk *dsk, struct blk_mq_tag_set *set)
{
	BUG_ON(!dsk);
	BUG_ON(!set);

	set->ops = &cas_mq_ops;
	set->nr_hw_queues = num_online_cpus();
	set->numa_node = NUMA_NO_NODE;
	/*TODO: Should we inherit qd from core device? */
	set->queue_depth = CAS_BLKDEV_DEFAULT_RQ;

	set->cmd_size = 0;
	set->flags = CAS_BLK_MQ_F_SHOULD_MERGE | CAS_BLK_MQ_F_STACKING |
			CAS_BLK_MQ_F_BLOCKING;

	set->driver_data = dsk;

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
	struct cas_disk *dsk = gd->private_data;
	struct cas_exp_obj *exp_obj = dsk->exp_obj;

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

int cas_exp_obj_create(struct cas_disk *dsk, const char *dev_name,
		struct module *owner, struct cas_exp_obj_ops *ops, void *priv)
{
	struct cas_exp_obj *exp_obj;
	struct request_queue *queue;
	struct gendisk *gd;
	cas_queue_limits_t queue_limits;
	int result = 0;

	BUG_ON(!owner);
	BUG_ON(!dsk);
	BUG_ON(!ops);
	BUG_ON(dsk->exp_obj);

	CAS_DEBUG_DISK_TRACE(dsk);

	if (strlen(dev_name) >= DISK_NAME_LEN)
		return -EINVAL;

	result = _cas_exp_obj_check_path(dev_name);
	if (result == -EEXIST) {
		printk(KERN_ERR "Could not activate exported object, "
				"because file /dev/%s exists.\n", dev_name);
	}

	if (result)
		return result;

	result = cas_exp_obj_alloc(dsk);
	if (result)
		return result;

	exp_obj = dsk->exp_obj;

	mutex_init(&exp_obj->openers_lock);

	exp_obj->dev_name = kstrdup(dev_name, GFP_KERNEL);
	if (!exp_obj->dev_name) {
		result = -ENOMEM;
		goto error_kstrdup;
	}

	if (!try_module_get(owner)) {
		CAS_DEBUG_DISK_ERROR(dsk, "Cannot get reference to module");
		result = -ENAVAIL;
		goto error_module_get;
	}
	exp_obj->owner = owner;
	exp_obj->ops = ops;

	result = _cas_init_tag_set(dsk, &exp_obj->tag_set);
	if (result) {
		goto error_init_tag_set;
	}

	if (exp_obj->ops->set_queue_limits) {
		result = exp_obj->ops->set_queue_limits(dsk, priv,
				&queue_limits);
		if (result)
			goto error_set_queue_limits;
	}

	result = cas_alloc_disk(&gd, &queue, &exp_obj->tag_set,
			&queue_limits);
	if (result) {
		goto error_alloc_mq_disk;
	}

	exp_obj->gd = gd;

	result = _cas_exp_obj_set_dev_t(dsk, gd);
	if (result)
		goto error_exp_obj_set_dev_t;

	BUG_ON(queue->queuedata);
	queue->queuedata = dsk;
	exp_obj->queue = queue;

	exp_obj->private = priv;

	_cas_init_queues(dsk);

	gd->fops = &_cas_exp_obj_ops;
	gd->private_data = dsk;
	strscpy(gd->disk_name, exp_obj->dev_name, sizeof(gd->disk_name));

	cas_blk_queue_make_request(queue, _cas_exp_obj_make_rq_fn);

	if (exp_obj->ops->set_geometry) {
		result = exp_obj->ops->set_geometry(dsk, exp_obj->private);
		if (result)
			goto error_set_geometry;
	}

	result = cas_add_disk(gd);
	if (result)
		goto error_add_disk;

	result = sysfs_create_group(&disk_to_dev(gd)->kobj, &device_attr_group);
	if (result)
		goto error_sysfs;

	result = bd_claim_by_disk(cas_disk_get_blkdev(dsk), dsk, gd);
	if (result)
		goto error_bd_claim;

	return 0;

error_bd_claim:
	sysfs_remove_group(&disk_to_dev(gd)->kobj, &device_attr_group);
error_sysfs:
	del_gendisk(dsk->exp_obj->gd);
error_add_disk:
error_set_geometry:
	exp_obj->private = NULL;
	_cas_exp_obj_clear_dev_t(dsk);
error_exp_obj_set_dev_t:
	cas_cleanup_disk(gd);
	exp_obj->gd = NULL;
error_alloc_mq_disk:
error_set_queue_limits:
	blk_mq_free_tag_set(&exp_obj->tag_set);
error_init_tag_set:
	module_put(owner);
	dsk->exp_obj->owner = NULL;
error_module_get:
	kfree(exp_obj->dev_name);
error_kstrdup:
	cas_exp_obj_free(dsk);
	return result;

}

int cas_exp_obj_destroy(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj;

	BUG_ON(!dsk);

	if (!dsk->exp_obj)
		return -ENODEV;

	CAS_DEBUG_DISK_TRACE(dsk);

	exp_obj = dsk->exp_obj;

	bd_release_from_disk(cas_disk_get_blkdev(dsk), exp_obj->gd);
	_cas_exp_obj_clear_dev_t(dsk);
	del_gendisk(exp_obj->gd);

	if (exp_obj->queue)
		cas_cleanup_queue(exp_obj->queue);

	blk_mq_free_tag_set(&exp_obj->tag_set);

	put_disk(exp_obj->gd);

	return 0;
}

void cas_exp_obj_cleanup(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj;
	struct module *owner;

	CAS_DEBUG_DISK_TRACE(dsk);

	exp_obj = dsk->exp_obj;

	if (!exp_obj)
		return;

	owner = exp_obj->owner;

	kfree(exp_obj->dev_name);
	cas_exp_obj_free(dsk);

	if (owner)
		module_put(owner);
}

int cas_exp_obj_lock(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj;
	int result = -EBUSY;

	BUG_ON(!dsk);
	BUG_ON(!dsk->exp_obj);

	CAS_DEBUG_DISK_TRACE(dsk);

	exp_obj = dsk->exp_obj;

	mutex_lock(&exp_obj->openers_lock);

	if (exp_obj->openers == 0) {
		exp_obj->claimed = true;
		result = 0;
	}

	mutex_unlock(&exp_obj->openers_lock);
	return result;
}

int cas_exp_obj_unlock(struct cas_disk *dsk)
{
	struct cas_exp_obj *exp_obj;

	BUG_ON(!dsk);
	CAS_DEBUG_DISK_TRACE(dsk);

	exp_obj = dsk->exp_obj;

	mutex_lock(&exp_obj->openers_lock);
	exp_obj->claimed = false;
	mutex_unlock(&exp_obj->openers_lock);

	return 0;
}

struct request_queue *cas_exp_obj_get_queue(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->exp_obj);
	return dsk->exp_obj->queue;
}

struct gendisk *cas_exp_obj_get_gendisk(struct cas_disk *dsk)
{
	BUG_ON(!dsk);
	BUG_ON(!dsk->exp_obj);
	return dsk->exp_obj->gd;
}
