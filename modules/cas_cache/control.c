/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <linux/cdev.h>
#include <linux/fs.h>
#include "linux_kernel_version.h"
#include "service_ui_ioctl.h"
#include "control.h"
#include "cas_cache/cas_cache.h"

struct cas_ctrl_device {
	struct cdev cdev;
	struct class *class;
	dev_t dev;
};

static struct cas_ctrl_device _control_device;

static const struct file_operations _ctrl_dev_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = cas_service_ioctl_ctrl
};

int __init cas_ctrl_device_init(void)
{
	struct cas_ctrl_device *ctrl = &_control_device;
	struct device *device;
	int result = 0;

	result = alloc_chrdev_region(&ctrl->dev, 0, 1, "cas");
	if (result) {
		printk(KERN_ERR "Cannot allocate control chrdev number.\n");
		goto error_alloc_chrdev_region;
	}

	cdev_init(&ctrl->cdev, &_ctrl_dev_fops);

	result = cdev_add(&ctrl->cdev, ctrl->dev, 1);
	if (result) {
		printk(KERN_ERR "Cannot add control chrdev.\n");
		goto error_cdev_add;
	}

	ctrl->class = class_create(THIS_MODULE, "cas");
	if (IS_ERR(ctrl->class)) {
		printk(KERN_ERR "Cannot create control chrdev class.\n");
		result = PTR_ERR(ctrl->class);
		goto error_class_create;
	}

	device = device_create(ctrl->class, NULL, ctrl->dev, NULL,
			"cas_ctrl");
	if (IS_ERR(device)) {
		printk(KERN_ERR "Cannot create control chrdev.\n");
		result = PTR_ERR(device);
		goto error_device_create;
	}

	return result;

error_device_create:
	class_destroy(ctrl->class);
error_class_create:
	cdev_del(&ctrl->cdev);
error_cdev_add:
	unregister_chrdev_region(ctrl->dev, 1);
error_alloc_chrdev_region:
	return result;
}

void __exit cas_ctrl_device_deinit(void)
{
	struct cas_ctrl_device *ctrl = &_control_device;

	device_destroy(ctrl->class, ctrl->dev);
	class_destroy(ctrl->class);
	cdev_del(&ctrl->cdev);
	unregister_chrdev_region(ctrl->dev, 1);
}
