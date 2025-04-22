/*
* Copyright(c) 2012-2021 Intel Corporation
* Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef UTILS_GC_H_
#define UTILS_GC_H_


void cas_garbage_collector_init(void);

void cas_garbage_collector_deinit(void);

void cas_vfree(const void *addr);
int cas_starting_cpu(unsigned int cpu);
int cas_ending_cpu(unsigned int cpu);

#endif /* UTILS_GC_H_ */
