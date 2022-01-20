/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "utils_blk.h"

int cas_blk_get_part_count(struct block_device *bdev)
{
	struct disk_part_tbl *ptbl;
	int i, count = 0;

	rcu_read_lock();
	ptbl = rcu_dereference(bdev->bd_disk->part_tbl);
	for (i = 0; i < ptbl->len; ++i) {
		if (rcu_access_pointer(ptbl->part[i]))
			count++;
	}
	rcu_read_unlock();

	return count;
}
