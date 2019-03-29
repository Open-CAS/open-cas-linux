/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/


#ifndef __THREADS_H__
#define __THREADS_H__

#include "ocf/ocf.h"
#include "linux_kernel_version.h"

#define CAS_CPUS_ALL -1

int cas_create_queue_thread(ocf_queue_t q, int cpu);
void cas_kick_queue_thread(ocf_queue_t q);
void cas_stop_queue_thread(ocf_queue_t q);

int cas_create_cleaner_thread(ocf_cleaner_t c);
void cas_stop_cleaner_thread(ocf_cleaner_t c);

int cas_create_metadata_updater_thread(ocf_metadata_updater_t mu);
void cas_kick_metadata_updater_thread(ocf_metadata_updater_t mu);
void cas_stop_metadata_updater_thread(ocf_metadata_updater_t mu);

#endif /* __THREADS_H__ */
