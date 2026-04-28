/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLOCK_DEV_BOTTOM_H__
#define __VOL_BLOCK_DEV_BOTTOM_H__

#include "../disk.h"

struct cas_priv_bottom {
	struct cas_disk *dsk;

	struct block_device *btm_bd;

	uint32_t opened_by_bdev : 1;
		/*!< Opened by supplying bdev manually */
};

static inline struct cas_priv_bottom *cas_get_priv_bottom(ocf_volume_t vol)
{
	return ocf_volume_get_priv(vol);
}

int block_dev_init(void);

int cas_volume_open_by_bdev(ocf_volume_t *vol, struct block_device *bdev);

void cas_volume_close(ocf_volume_t vol);

#endif /* __VOL_BLOCK_DEV_BOTTOM_H__ */
