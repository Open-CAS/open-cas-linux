/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef OCF_ENV_H_
#define OCF_ENV_H_

#include <string.h>
#include <stdlib.h>
#include "safeclib/safe_lib.h"

/**
 * @def min(a,b)
 * @brief checks which number is lower
 */
#define min(x, y)  ({ x < y ? x : y; })

/** @addtogroup DEBUGGING
 * definitions for debugging macros - warns and asserts
 * @{
 */

/**
 * @def ENV_BUG_ON(cond)
 * @brief checks if \a cond makes program pointless and program
 * should terminate with error
 */
#define ENV_BUG_ON(cond) ({ if (cond) exit(1); })
/** @} */

/** @addtogroup STRING_OPERATIONS 
 * definitions for custom string operations
 * @{
 */

/**
 * @def env_memset
 * @brief macro to use secure \a memset_s
 */
#define env_memset memset_s

/**
 * @def env_memcpy
 * @brief macro to use secure \a memcpy_s
 */
#define env_memcpy memcpy_s

/**
 * @def env_memcmp
 * @brief macro to use secure \a memcmp_s
 */
#define env_memcmp memcmp_s

/**
 * @def env_strnlen
 * @brief macro to use secure \a strnlen_s
 */
#define env_strnlen strnlen_s

/**
 * @def env_strncmp
 * @brief macro to use \a strncmp
 */
#define env_strncmp strncmp

/**
 * @def env_strncpy
 * @brief macro to use secure \a strncpy_s
 */
#define env_strncpy strncpy_s
/** @} */

#endif /* OCF_ENV_H_ */
