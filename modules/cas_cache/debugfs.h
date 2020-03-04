/*
* Copyright(c) 2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __DEBUGFS_H__
#define __DEBUGFS_H__

#include "cas_cache.h"

int cas_debugfs_add_cache(ocf_cache_t cache);
void cas_debugfs_remove_cache(ocf_cache_t cache);

int cas_debugfs_add_core(ocf_core_t core);
void cas_debugfs_remove_core(ocf_core_t core);

int cas_debugfs_init(void);
void cas_debugfs_deinit(void);

#endif /* __DEBUGFS_H__ */
