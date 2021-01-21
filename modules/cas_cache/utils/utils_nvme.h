/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef UTILS_NVME_H_
#define UTILS_NVME_H_

#if defined(CAS_UAPI_NVME)
#include <uapi/nvme.h>
#endif

#if defined(CAS_UAPI_LINUX_NVME)
#include <uapi/linux/nvme.h>
#endif

#if defined(CAS_UAPI_LINUX_NVME_IOCTL)
#include <uapi/linux/nvme_ioctl.h>
#endif

#include <linux/nvme.h>

int cas_nvme_get_nsid(struct block_device *bdev, unsigned int *nsid);
int cas_nvme_identify_ns(struct block_device *bdev, unsigned int nsid,
		struct nvme_id_ns *ns);


#endif /* UTILS_NVME_H_ */
