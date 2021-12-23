/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLOCK_DEV_TOP_H__
#define __VOL_BLOCK_DEV_TOP_H__


int kcas_core_create_exported_object(ocf_core_t core);
int kcas_core_destroy_exported_object(ocf_core_t core);
int kcas_core_activate_exported_object(ocf_core_t core);

int kcas_cache_destroy_all_core_exported_objects(ocf_cache_t cache);

int kcas_cache_create_exported_object(ocf_cache_t cache);
int kcas_cache_destroy_exported_object(ocf_cache_t cache);
int kcas_cache_activate_exported_object(ocf_cache_t cache);

#endif /* __VOL_BLOCK_DEV_TOP_H__ */
