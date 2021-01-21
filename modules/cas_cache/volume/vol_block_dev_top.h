/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __VOL_BLOCK_DEV_TOP_H__
#define __VOL_BLOCK_DEV_TOP_H__

int block_dev_activate_all_exported_objects(ocf_cache_t cache);
int block_dev_activate_exported_object(ocf_core_t core);

int block_dev_create_all_exported_objects(ocf_cache_t cache);
int block_dev_create_exported_object(ocf_core_t core);

int block_dev_destroy_all_exported_objects(ocf_cache_t cache);
int block_dev_destroy_exported_object(ocf_core_t core);

int block_dev_free_all_exported_objects(ocf_cache_t cache);

#endif /* __VOL_BLOCK_DEV_TOP_H__ */
