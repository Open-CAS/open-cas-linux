/*
* Copyright(c) 2012-2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils_nvme.h"
#include "utils_blk.h"

#include <linux/ioctl.h>
#include <linux/file.h>
#include <linux/nvme_ioctl.h>


int cas_nvme_get_nsid(struct block_device *bdev, unsigned int *nsid)
{
	int ret = 0;

	/*
	 * Maximum NSID is 0xFFFFFFFF, so theoretically there is no free
	 * room for error code. However it's unlikely that there will ever
	 * be device with such number of namespaces, so we treat this value
	 * as it was signed. Then in case of negative value we interpret it
	 * as an error code. Moreover in case of error we can be sure, that
	 * we deal with non-NVMe device, because this ioctl should never
	 * fail with NVMe driver.
	 */
	ret = ioctl_by_bdev(bdev, NVME_IOCTL_ID, (unsigned long)NULL);
	if (ret < 0)
		return ret;

	*nsid = (unsigned int)ret;
	return 0;
}

#define NVME_ID_CNS_NS 0x00
#define NVME_ID_CNS_CTRL 0x01

int cas_nvme_identify_ns(struct block_device *bdev, unsigned int nsid,
		struct nvme_id_ns *ns)
{
	struct nvme_admin_cmd cmd = { };
	unsigned long __user buffer;
	int ret = 0;

	buffer = cas_vm_mmap(NULL, 0, sizeof(*ns));
	if (IS_ERR((void *)buffer))
		return PTR_ERR((void *)buffer);

	cmd.opcode = nvme_admin_identify;
	cmd.nsid = cpu_to_le32(nsid);
	cmd.addr = (__u64)buffer;
	cmd.data_len = sizeof(*ns);
	cmd.cdw10 = NVME_ID_CNS_NS;
	ret = ioctl_by_bdev(bdev, NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	if (ret < 0)
		goto out;

	ret = copy_from_user(ns, (void *)buffer, sizeof(*ns));
	if (ret > 0)
		ret = -EINVAL;
out:
	cas_vm_munmap(buffer, sizeof(*ns));
	return ret;
}
