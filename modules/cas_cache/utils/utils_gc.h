/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef UTILS_GC_H_
#define UTILS_GC_H_


void cas_garbage_collector_init(void);

void cas_garbage_collector_deinit(void);

void cas_vfree(const void *addr);

#endif /* UTILS_GC_H_ */
