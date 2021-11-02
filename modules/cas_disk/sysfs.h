/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_SYSFS_H__
#define __CASDISK_SYSFS_H__

#include <linux/kobject.h>
#include <linux/sysfs.h>

struct casdsk_disk;

struct casdsk_attribute {
	struct attribute attr;
	ssize_t (*show)(struct kobject *kobj, char *page);
	ssize_t (*store)(struct kobject *kobj, const char *buf, size_t len);
};

extern const struct sysfs_ops casdsk_sysfs_ops;

#endif
