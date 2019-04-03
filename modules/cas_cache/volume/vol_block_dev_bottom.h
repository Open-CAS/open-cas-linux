/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __VOL_BLOCK_DEV_BOTTOM_H__
#define __VOL_BLOCK_DEV_BOTTOM_H__

#include "../cas_cache.h"

int block_dev_open_object(ocf_volume_t vol, void *volume_params);

void block_dev_close_object(ocf_volume_t vol);

const char *block_dev_get_elevator_name(struct request_queue *q);

int block_dev_is_metadata_mode_optimal(struct atomic_dev_params *atomic_params,
		uint8_t type);

int block_dev_try_get_io_class(struct bio *bio, int *io_class);

int block_dev_init(void);

void block_dev_deinit(void);

#endif /* __VOL_BLOCK_DEV_BOTTOM_H__ */
