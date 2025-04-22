/*
* Copyright(c) 2012-2021 Intel Corporation
* Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef OCF_ENV_H_
#define OCF_ENV_H_

#include <string.h>
#include <stdlib.h>
#include "safeclib/safe_lib.h"

#define min(x, y)  ({ x < y ? x : y; })

/* *** STRING OPERATIONS *** */

#define env_memset memset_s
#define env_memcpy memcpy_s
#define env_memcmp memcmp_s

#define env_strnlen strnlen_s
#define env_strncmp strncmp
#define env_strncpy strncpy_s
#define env_get_tick_count() 0

#endif /* OCF_ENV_H_ */
