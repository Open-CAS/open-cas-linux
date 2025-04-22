/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __OBJ_BLK_H__
#define __OBJ_BLK_H__

#include "vol_block_dev_bottom.h"
#include "vol_block_dev_top.h"

struct cas_disk;

struct bd_object {
	struct cas_disk *dsk;

	struct block_device *btm_bd;

	uint32_t expobj_valid : 1;
		/*!< Bit indicates that exported object was created */

	uint32_t expobj_locked : 1;
		/*!< Non zero value indicates data exported object is locked */

	uint32_t opened_by_bdev : 1;
		/*!< Opened by supplying bdev manually */

	struct workqueue_struct *expobj_wq;
		/*< Workqueue for I/O handled by top vol */

	ocf_volume_t front_volume;
		/*< Cache/core front volume */
};

static inline struct bd_object *bd_object(ocf_volume_t vol)
{
	return ocf_volume_get_priv(vol);
}

#endif /* __OBJ_BLK_H__ */
