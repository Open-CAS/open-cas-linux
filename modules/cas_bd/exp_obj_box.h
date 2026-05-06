/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef __CAS_BD_BOX_H__
#define __CAS_BD_BOX_H__

#include "disk.h"
#include "exp_obj.h"

/**
 * @brief Put exported object into the box
 *
 * Transfers ownership of the exported object to cas_bd. The exp_obj
 * is stored in whatever state the caller left it (frozen, pass-through,
 * etc.) and can be stopped via sysfs.
 *
 * @param exp_obj Pointer to exported object
 */
void cas_exp_obj_box_deposit(struct cas_exp_obj *exp_obj);

/**
 * @brief Claim exported object from the box by its underlying disk
 * @param dsk Pointer to cas_disk
 * @param owner Pointer to cas module
 * @param ops Pointer to structure with callback functions
 * @param priv Private data
 * @return Pointer to exp_obj on success, ERR_PTR on failure
 */
struct cas_exp_obj *cas_exp_obj_box_claim(struct cas_disk *dsk,
		struct module *owner, struct cas_exp_obj_ops *ops, void *priv);

#endif
