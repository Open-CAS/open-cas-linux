/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_DISK_H__
#define __CASDISK_DISK_H__

#include <linux/kobject.h>
#include <linux/fs.h>
#include <linux/blkdev.h>
#include <linux/mutex.h>
#include <linux/blk-mq.h>
#include "cas_cache.h"

struct casdsk_exp_obj;

struct casdsk_disk {
	uint32_t id;
	char *path;

	struct mutex openers_lock;
	unsigned int openers;
	bool claimed;

	struct block_device *bd;

	int gd_flags;
	int gd_minors;

	struct blk_mq_tag_set tag_set;
	struct casdsk_exp_obj *exp_obj;

	struct kobject kobj;
	struct list_head list;

	void *private;
};

int __init casdsk_init_disks(void);
void casdsk_deinit_disks(void);

int casdsk_disk_allocate_minors(int count);

/**
 * @brief Open block device
 * @param path Path to block device
 * @param private Private data
 * @return Pointer to casdsk_disk related to opened block device
 */
struct casdsk_disk *casdsk_disk_open(const char *path, void *private);

/**
 * @brief Claim previously opened block device (holded by cas_disk)
 * @param path Path to block device
 * @param private Private data
 * @return Pointer to casdsk_disk structure related to block device, or NULL
 *	if device is not opened by cas_disk.
 */
struct casdsk_disk *casdsk_disk_claim(const char *path, void *private);

/**
 * @brief Close block device and remove from cas_disk
 * @param dsk Pointer to casdsk_disk structure related to block device
 *	which should be closed.
 */
void casdsk_disk_close(struct casdsk_disk *dsk);

/**
 * @brief Get block_device structure of bottom block device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return Pointer to block_device structure of bottom block device
 */
struct block_device *casdsk_disk_get_blkdev(struct casdsk_disk *dsk);

/**
 * @brief Get request queue of bottom block device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return Pointer to reqest_queue structure of bottom block device
 */
struct request_queue *casdsk_disk_get_queue(struct casdsk_disk *dsk);

/**
 * @brief Get gendisk structure of bottom block device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return Pointer to gendisk structure of bottom block device
 */
struct gendisk *casdsk_disk_get_gendisk(struct casdsk_disk *dsk);

#endif
