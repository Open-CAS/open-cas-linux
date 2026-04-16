/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLOCK_DEV_BOTTOM_H__
#define __VOL_BLOCK_DEV_BOTTOM_H__
int block_dev_init(void);

int cas_volume_open_by_bdev(ocf_volume_t *vol, struct block_device *bdev);

void cas_volume_close(ocf_volume_t vol);

#endif /* __VOL_BLOCK_DEV_BOTTOM_H__ */
