/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_DISK_H__
#define __CASDISK_DISK_H__

#include <linux/fs.h>
#include <linux/blkdev.h>
#include <linux/mutex.h>
#include <linux/blk-mq.h>
#include "cas_cache.h"

struct cas_exp_obj;

struct cas_disk {
	char *path;

	struct block_device *bd;

	struct cas_exp_obj *exp_obj;
};

int __init cas_init_disks(void);
void cas_deinit_disks(void);

/**
 * @brief Open block device
 * @param path Path to block device
 * @return Pointer to cas_disk related to opened block device
 */
struct cas_disk *cas_disk_open(const char *path);

/**
 * @brief Close block device and remove from cas
 * @param dsk Pointer to cas_disk structure related to block device
 *	which should be closed.
 */
void cas_disk_close(struct cas_disk *dsk);

/**
 * @brief Get block_device structure of bottom block device
 * @param dsk Pointer to cas_disk structure representing a block device
 * @return Pointer to block_device structure of bottom block device
 */
struct block_device *cas_disk_get_blkdev(struct cas_disk *dsk);

/**
 * @brief Get request queue of bottom block device
 * @param dsk Pointer to cas_disk structure representing a block device
 * @return Pointer to reqest_queue structure of bottom block device
 */
struct request_queue *cas_disk_get_queue(struct cas_disk *dsk);

/**
 * @brief Get gendisk structure of bottom block device
 * @param dsk Pointer to cas_disk structure representing a block device
 * @return Pointer to gendisk structure of bottom block device
 */
struct gendisk *cas_disk_get_gendisk(struct cas_disk *dsk);

#endif
