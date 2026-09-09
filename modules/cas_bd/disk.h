/*
 * Copyright(c) 2012-2022 Intel Corporation
 * Copyright(c) 2024 Huawei Technologies
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __CAS_BD_DISK_H__
#define __CAS_BD_DISK_H__

struct cas_disk;

/**
 * @brief Open block device exclusively
 *
 * @param path Path to block device
 * @return Pointer to cas_disk related to opened block device, or ERR_PTR
 */
struct cas_disk *cas_disk_open(const char *path);

/**
 * @brief Release exclusive claim on block device
 * @param dsk Pointer to cas_disk structure
 */
void cas_disk_release(struct cas_disk *dsk);

/**
 * @brief Increment reference count of cas_disk
 * @param dsk Pointer to cas_disk structure
 */
void cas_disk_get(struct cas_disk *dsk);

/**
 * @brief Decrement refcount of block device, close and deinit it at zero
 * @param dsk Pointer to cas_disk structure
 */
void cas_disk_put(struct cas_disk *dsk);

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
