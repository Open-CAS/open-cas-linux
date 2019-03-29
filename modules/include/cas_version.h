/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __CAS_VERSION_H__
#define __CAS_VERSION_H__

#if !defined(CAS_BUILD_NO)
#error "You must define build number for version"
#endif

#define STR_PREP(x) #x
#define PR_STR(x) STR_PREP(x)
#define FMT_VERSION(x) "0" PR_STR(x)

#ifdef CAS_BUILD_FLAG
#define CAS_VERSION_FLAG "-"CAS_BUILD_FLAG
#else
#define CAS_VERSION_FLAG ""
#endif

#define CAS_VERSION \
	FMT_VERSION(CAS_VERSION_MAIN) "." \
	FMT_VERSION(CAS_VERSION_MAJOR) "." \
	FMT_VERSION(CAS_VERSION_MINOR) "." \
	CAS_BUILD_NO \
	CAS_VERSION_FLAG

#endif
