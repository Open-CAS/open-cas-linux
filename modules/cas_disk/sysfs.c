/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#include "cas_disk_defs.h"
#include "sysfs.h"

static ssize_t _casdsk_sysfs_show(struct kobject *kobj, struct attribute *attr,
				char *page)
{
	struct casdsk_attribute *casdsk_attr =
		container_of(attr, struct casdsk_attribute, attr);

	if (!casdsk_attr->show)
		return -EIO;

	return casdsk_attr->show(kobj, page);
}

static ssize_t _casdsk_sysfs_store(struct kobject *kobj, struct attribute *attr,
		const char *buf, size_t len)
{
	struct casdsk_attribute *casdsk_attr =
			container_of(attr, struct casdsk_attribute, attr);

	if (!casdsk_attr->store)
		return -EIO;

	return casdsk_attr->store(kobj, buf, len);
}

const struct sysfs_ops casdsk_sysfs_ops = {
	.show = _casdsk_sysfs_show,
	.store = _casdsk_sysfs_store
};
