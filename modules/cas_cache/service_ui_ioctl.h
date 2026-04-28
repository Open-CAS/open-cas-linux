/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __SERVICE_UI_IOCTL_H__

#define __SERVICE_UI_IOCTL_H__

long cas_service_ioctl_ctrl(struct file *filp, unsigned int cmd,
		unsigned long arg);

#endif
