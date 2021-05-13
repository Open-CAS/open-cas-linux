/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/
#ifndef __CASDISK_H__
#define __CASDISK_H__

#include <linux/blkdev.h>
#include "linux_kernel_version.h"

/**
 * Version of cas_disk interface
 */
#define CASDSK_IFACE_VERSION 2

struct casdsk_disk;

#define CASDSK_BIO_NOT_HANDLED 0
#define CASDSK_BIO_HANDLED 1

struct casdsk_exp_obj_ops {

	/**
	 * @brief Prepare request queue of exported object (top) block device.
	 *	Could be NULL.
	 */
	int (*prepare_queue)(struct casdsk_disk *dsk, struct request_queue *q,
			     void *private);

	/**
	 * @brief Cleanup request queue of exported object (top) block device.
	 *	Could be NULL.
	 */
	void (*cleanup_queue)(struct casdsk_disk *dsk);

	/**
	 * @brief Set geometry of exported object (top) block device.
	 *	Could be NULL.
	 */
	int (*set_geometry)(struct casdsk_disk *dsk, void *private);

	/**
	 * @brief make_request_fn of exported object (top) block device.
	 * Called by cas_disk when cas_disk device is in attached mode.
	 *
	 * @return casdsk_BIO_HANDLED when bio was handled.
	 * Otherwise casdsk_BIO_NOT_HANDLED. In this case bio will be submitted
	 * to I/O scheduler and should be handled by request_fn.
	 */
	int (*make_request_fn)(struct casdsk_disk *dsk, struct request_queue *q,
			       struct bio *bio, void *private);

	/**
	 * @brief queue_rq_fn of exported object (top) block device.
	 * Called by cas_disk when cas_disk device is in attached mode.
	 */
	CAS_BLK_STATUS_T (*queue_rq_fn)(struct casdsk_disk *dsk, struct request *rq,
			   void *private);

	/**
	 * @brief Increment exported object pending request counter.
	 */
	void (*pending_rq_inc)(struct casdsk_disk *dsk, void *private);

	/**
	 * @brief Decrement exported object pending request counter.
	 */
	void (*pending_rq_dec)(struct casdsk_disk *dsk, void *private);

	/**
	 * @brief ioctl handler of exported object (top) block device.
	 * Called by cas_disk when cas_disk device is in attached mode.
	 */
	int (*ioctl)(struct casdsk_disk *dsk, unsigned int cmd, unsigned long arg,
		     void *private);
};

/**
 * Stored configuration buffer description
 */
struct casdsk_props_conf {
	void *buffer;
	size_t size;
	uint16_t crc;
};

/**
 * @brief Get version of cas_disk interface
 * @return cas_disk interface version
 */
uint32_t casdsk_get_version(void);

/**
 * @brief Store configuration buffers in cas_disk
 * @param n_blobs Number of configuration buffers
 * @param blobs Array of configuration buffers structures
 */
void casdsk_store_config(size_t n_blobs, struct casdsk_props_conf *blobs);

/**
 * @brief Get previously stored configuration buffers
 * @param blobs Where to store pointer to configuration buffers array
 * @return Number of stored configuration buffers
 */
size_t casdsk_get_stored_config(struct casdsk_props_conf **blobs);

/**
 * @brief Free resources related to stored configuration buffers
 */
void casdsk_free_stored_config(void);

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

/**
 * @brief Prepare cas_disk device to switch to pass-through mode
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_disk_set_pt(struct casdsk_disk *dsk);

/**
 * @brief Prepare cas_disk device to switch to attached mode
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_disk_set_attached(struct casdsk_disk *dsk);

/**
 * @brief Revert cas_disk device back to attached mode
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_disk_clear_pt(struct casdsk_disk *dsk);

/**
 * @brief Dettach cas from cas_disk device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_disk_dettach(struct casdsk_disk *dsk);

/**
 * @brief Attach cas to cas_disk device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @param owner Pointer to cas module
 * @param ops Pointer to structure with callback functions
 * @return 0 if success, errno if failure
 */
int casdsk_disk_attach(struct casdsk_disk *dsk, struct module *owner,
		     struct casdsk_exp_obj_ops *ops);

/**
 * @brief Create exported object (top device)
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @param dev_name Name of exported object (top device)
 * @param owner Pointer to cas module
 * @param ops Pointer to structure with callback functions
 * @return 0 if success, errno if failure
 */
int casdsk_exp_obj_create(struct casdsk_disk *dsk, const char *dev_name,
			struct module *owner, struct casdsk_exp_obj_ops *ops);

/**
 * @brief Get request queue of exported object (top) block device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return Pointer to reqest_queue structure of top block device
 */
struct request_queue *casdsk_exp_obj_get_queue(struct casdsk_disk *dsk);

/**
 * @brief Get gendisk structure of exported object (top) block device
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return Pointer to gendisk structure of top block device
 */
struct gendisk *casdsk_exp_obj_get_gendisk(struct casdsk_disk *dsk);

/**
 * @brief Activate exported object (make it visible to OS
 *	and allow I/O handling)
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_exp_obj_activate(struct casdsk_disk *dsk);

/**
 * @brief Check if exported object is active
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return true if exported object is active
 */
bool casdsk_exp_obj_activated(struct casdsk_disk *ds);

/**
 * @brief Lock exported object
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_exp_obj_lock(struct casdsk_disk *dsk);

/**
 * @brief Unlock exported object
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_exp_obj_unlock(struct casdsk_disk *dsk);

/**
 * @brief Destroy exported object
 * @param dsk Pointer to casdsk_disk structure related to cas_disk device
 * @return 0 if success, errno if failure
 */
int casdsk_exp_obj_destroy(struct casdsk_disk *dsk);

#endif
