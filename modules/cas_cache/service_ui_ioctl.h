/*
* Copyright(c) 2012-2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __SERVICE_UI_IOCTL_H__

#define __SERVICE_UI_IOCTL_H__

struct casdsk_disk;

long cas_service_ioctl_ctrl(struct file *filp, unsigned int cmd,
		unsigned long arg);

#endif
