/*
* Copyright(c) 2012 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef UTILS_BLK_H_
#define UTILS_BLK_H_

#include <linux/fs.h>
#include <linux/genhd.h>

int cas_blk_get_part_count(struct block_device *bdev);

#endif /* UTILS_BLK_H_ */
