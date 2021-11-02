/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __VOL_BLOCK_DEV_BOTTOM_H__
#define __VOL_BLOCK_DEV_BOTTOM_H__

#include "../cas_cache.h"

int block_dev_open_object(ocf_volume_t vol, void *volume_params);

void block_dev_close_object(ocf_volume_t vol);

const char *block_dev_get_elevator_name(struct request_queue *q);

int block_dev_try_get_io_class(struct bio *bio, int *io_class);

int block_dev_init(void);

#endif /* __VOL_BLOCK_DEV_BOTTOM_H__ */
