/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __OCF_ENV_HEADERS_H__
#define __OCF_ENV_HEADERS_H__

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* TODO: Move prefix printing to context logger. */
#define OCF_LOGO "CAS"
#define OCF_PREFIX_SHORT "[" OCF_LOGO "] "
#define OCF_PREFIX_LONG "Cache Acceleration Software Linux"

#define OCF_VERSION_MAIN CAS_VERSION_MAIN
#define OCF_VERSION_MAJOR CAS_VERSION_MAJOR
#define OCF_VERSION_MINOR CAS_VERSION_MINOR

#endif /* __OCF_ENV_HEADERS_H__ */
