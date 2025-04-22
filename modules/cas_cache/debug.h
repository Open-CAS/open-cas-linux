/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_DEBUG_H__
#define __CASDISK_DEBUG_H__

#undef CAS_DEBUG

#ifdef CAS_DEBUG
#define CAS_DEBUG_TRACE()						\
	printk(KERN_INFO "%s\n", __func__)

#define CAS_DEBUG_DISK_TRACE(dsk)					\
	printk(KERN_INFO "[%s] %s\n", dsk->path,  __func__)

#define CAS_DEBUG_MSG(msg)						\
	printk(KERN_INFO "%s - %s\n", __func__, msg)

#define CAS_DEBUG_PARAM(format, ...)					\
	printk(KERN_INFO "%s - "format"\n",			\
	       __func__, ##__VA_ARGS__)

#define CAS_DEBUG_DISK(dsk, format, ...)				\
	printk(KERN_INFO "[%s] %s - "format"\n",			\
	       dsk->path,						\
	       __func__, ##__VA_ARGS__)

#define CAS_DEBUG_ERROR(error, ...)					\
	CAS_DEBUG_PARAM("ERROR(%d) "error, __LINE__, ##__VA_ARGS__)

#define CAS_DEBUG_DISK_ERROR(dsk, error, ...)				\
	CAS_DEBUG_DISK(dsk, "ERROR(%d) "error, __LINE__, ##__VA_ARGS__)

#else
#define CAS_DEBUG_TRACE()
#define CAS_DEBUG_DISK_TRACE(dsk)
#define CAS_DEBUG_MSG(msg)
#define CAS_DEBUG_PARAM(format, ...)
#define CAS_DEBUG_DISK(dsk, format, ...)
#define CAS_DEBUG_ERROR(error, ...)
#define CAS_DEBUG_DISK_ERROR(dsk, error, ...)
#endif

#endif
