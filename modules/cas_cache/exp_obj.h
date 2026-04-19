/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024-2025 Huawei Technologies
* Copyright(c) 2026 Unvertical
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_EXP_OBJ_H__
#define __CASDISK_EXP_OBJ_H__

#include <linux/list.h>
#include <linux/mutex.h>
#include <linux/blk-mq.h>
#include "generated_defines.h"
#include "disk.h"

struct cas_exp_obj {
	struct cas_disk *dsk;

	struct gendisk *gd;
	struct request_queue *queue;

	struct block_device *locked_bd;

	struct module *owner;

	struct cas_exp_obj_ops *ops;

	const char *dev_name;

	struct mutex openers_lock;
	unsigned int openers;
	bool claimed;

	int minor_slot;

	struct blk_mq_tag_set tag_set;

	void *private;
};

int __init cas_init_exp_objs(void);

void cas_deinit_exp_objs(void);

struct cas_exp_obj_ops {
	/**
	 * @brief Set geometry of exported object (top) block device.
	 *	Could be NULL.
	 */
	int (*set_geometry)(struct cas_exp_obj *exp_obj);

	/**
	 * @brief Set queue limits of exported object (top) block device.
	 */
	int (*set_queue_limits)(struct cas_exp_obj *exp_obj,
			cas_queue_limits_t *lim);

	/**
	 * @brief submit_bio of exported object (top) block device.
	 *
	 */
	void (*submit_bio)(struct cas_exp_obj *exp_obj, struct bio *bio);
};

/**
 * @brief Create exported object (top device)
 * @param dsk Pointer to a structure representing a backend block device
 * @param dev_name Name of exported object (top device)
 * @param owner Pointer to cas module
 * @param ops Pointer to structure with callback functions
 * @param priv Private data
 * @return Pointer to an exported object
 */
struct cas_exp_obj *cas_exp_obj_create(struct cas_disk *dsk,
		const char *dev_name, struct module *owner,
		struct cas_exp_obj_ops *ops, void *priv);

/**
 * @brief Dismantle exported object
 * @param exp_obj Pointer to a structure representing a front block device
 * @return 0 if success, errno if failure
 */
int cas_exp_obj_dismantle(struct cas_exp_obj *exp_obj);

/**
 * @brief Destroy exported object
 * @param exp_obj Pointer to a structure representing a front block device
 * @return 0 if success, errno if failure
 */
void cas_exp_obj_destroy(struct cas_exp_obj *exp_obj);

/**
 * @brief Lock exported object
 * @param exp_obj Pointer to a structure representing a front block device
 * @return 0 if success, errno if failure
 */
int cas_exp_obj_lock(struct cas_exp_obj *exp_obj);

/**
 * @brief Unlock exported object
 * @param exp_obj Pointer to a structure representing a front block device
 * @return 0 if success, errno if failure
 */
int cas_exp_obj_unlock(struct cas_exp_obj *exp_obj);

/**
 * @brief Set exported object priv
 * @param exp_obj Pointer to a structure representing a front block device
 * @param priv Private data
 */
void cas_exp_obj_set_priv(struct cas_exp_obj *exp_obj, void *priv);

/**
 * @brief Get exported object priv
 * @param exp_obj Pointer to a structure representing a front block device
 * @return Private data
 */
void *cas_exp_obj_get_priv(struct cas_exp_obj *exp_obj);

/**
 * @brief Get request queue of exported object (top) block device
 * @param exp_obj Pointer to a structure representing a front block device
 * @return Pointer to reqest_queue structure of top block device
 */
struct request_queue *cas_exp_obj_get_queue(struct cas_exp_obj *exp_obj);

/**
 * @brief Get gendisk structure of exported object (top) block device
 * @param exp_obj Pointer to a structure representing a front block device
 * @return Pointer to gendisk structure of top block device
 */
struct gendisk *cas_exp_obj_get_gendisk(struct cas_exp_obj *exp_obj);

#endif
