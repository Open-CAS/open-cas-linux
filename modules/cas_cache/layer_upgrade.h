/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __LAYER_UPGRADE_H

#define __LAYER_UPGRADE_H

#include "cas_cache/cas_cache.h"

extern bool in_upgrade;

/**
 * @brief Check that CAS is in upgarde state
 * @return true if is or false if isn't
 */
bool cas_upgrade_is_in_upgrade(void);

/**
 * @brief Check that caches configuration is stored at casdsk
 * @return 0 if exist
 */
int cas_upgrade_get_configuration(void);

/**
 * @brief Start upgrade in flight procedure, dump configuration,
 *          switch caches to PT and close caches
 * @return result
 */
int cas_upgrade(void);

/**
 * @brief Finish upgrade in new CAS module - restore all caches
 * @return result of restoring
 */
int cas_upgrade_finish(void);

/**
 * @brief Try to parse configuration stored in casdisk
 * @return result of verification
 */
int cas_upgrade_verify(void);

#endif /* __LAYER_UPGRADE_H */

