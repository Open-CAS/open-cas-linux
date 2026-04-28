/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLOCK_DEV_TOP_H__
#define __VOL_BLOCK_DEV_TOP_H__

#include "ocf/ocf.h"
#include "../linux_kernel_version.h"
#include "../exp_obj.h"

struct cas_priv_top {
	struct cas_exp_obj *exp_obj;

	struct workqueue_struct *expobj_wq;
		/*< Workqueue for I/O handled by top vol */

	ocf_volume_t front_volume;
		/*< Cache/core front volume */

	uint32_t expobj_valid : 1;
		/*!< Bit indicates that exported object was created */

	uint32_t expobj_locked : 1;
		/*!< Non zero value indicates data exported object is locked */
};

static inline struct cas_priv_top *cas_get_priv_top(ocf_core_t core)
{
	return ocf_core_get_priv(core);
}

int kcas_core_create_exported_object(ocf_core_t core);
int kcas_core_destroy_exported_object(ocf_core_t core);

int kcas_cache_destroy_all_core_exported_objects(ocf_cache_t cache);

int kcas_cache_create_exported_object(ocf_cache_t cache);
int kcas_cache_destroy_exported_object(ocf_cache_t cache);

#endif /* __VOL_BLOCK_DEV_TOP_H__ */
