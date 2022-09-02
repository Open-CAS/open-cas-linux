/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_EXP_OBJ_H__
#define __CASDISK_EXP_OBJ_H__

#include <linux/kobject.h>
#include <linux/fs.h>

struct casdsk_disk;

struct casdsk_exp_obj_ops {
	/**
	 * @brief Set geometry of exported object (top) block device.
	 *	Could be NULL.
	 */
	int (*set_geometry)(struct casdsk_disk *dsk, void *private);

	/**
	 * @brief submit_bio of exported object (top) block device.
	 * Called by cas_disk when cas_disk device is in attached mode.
	 *
	 */
	void (*submit_bio)(struct casdsk_disk *dsk,
			       struct bio *bio, void *private);
};

struct casdsk_exp_obj {

	struct gendisk *gd;
	struct request_queue *queue;

	struct block_device *locked_bd;

	struct module *owner;

	bool activated;

	struct casdsk_exp_obj_ops *ops;

	const char *dev_name;
	struct kobject kobj;

	atomic_t pt_ios;
	atomic_t *pending_rqs;
};

int __init casdsk_init_exp_objs(void);
void casdsk_deinit_exp_objs(void);

void casdsk_exp_obj_free(struct casdsk_disk *dsk);

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
