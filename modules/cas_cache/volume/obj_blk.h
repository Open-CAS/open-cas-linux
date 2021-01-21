/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __OBJ_BLK_H__
#define __OBJ_BLK_H__

#include "vol_atomic_dev_bottom.h"
#include "vol_block_dev_bottom.h"
#include "vol_block_dev_top.h"

struct casdsk_disk;

struct bd_object {
	struct casdsk_disk *dsk;

	struct block_device *btm_bd;

	uint32_t expobj_valid : 1;
		/*!< Bit indicates that exported object was created */

	uint32_t expobj_locked : 1;
		/*!< Non zero value indicates data exported object is locked */

	uint32_t opened_by_bdev : 1;
		/*!< Opened by supplying bdev manually */

	struct atomic_dev_params atomic_params;

	atomic64_t pending_rqs;
		/*!< This fields describes in flight IO requests */

	struct workqueue_struct *workqueue;
		/*< Workqueue for internally trigerred I/O */
};

static inline struct bd_object *bd_object(ocf_volume_t vol)
{
	return ocf_volume_get_priv(vol);
}

#endif /* __OBJ_BLK_H__ */
