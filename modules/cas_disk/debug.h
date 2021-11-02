/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __CASDISK_DEBUG_H__
#define __CASDISK_DEBUG_H__

#undef CASDSK_DEBUG

#ifdef CASDSK_DEBUG
#define CASDSK_DEBUG_TRACE()						\
	printk(CASDSK_KERN_INFO "%s\n", __func__)

#define CASDSK_DEBUG_DISK_TRACE(dsk)					\
	printk(CASDSK_KERN_INFO "[%u] %s\n", dsk->id,  __func__)

#define CASDSK_DEBUG_MSG(msg)						\
	printk(CASDSK_KERN_INFO "%s - %s\n", __func__, msg)

#define CASDSK_DEBUG_PARAM(format, ...)					\
	printk(CASDSK_KERN_INFO "%s - "format"\n",			\
	       __func__, ##__VA_ARGS__)

#define CASDSK_DEBUG_DISK(dsk, format, ...)				\
	printk(CASDSK_KERN_INFO "[%u] %s - "format"\n",			\
	       dsk->id,							\
	       __func__, ##__VA_ARGS__)

#define CASDSK_DEBUG_ERROR(error, ...)					\
	CASDSK_DEBUG_PARAM("ERROR(%d) "error, __LINE__, ##__VA_ARGS__)

#define CASDSK_DEBUG_DISK_ERROR(dsk, error, ...)				\
	CASDSK_DEBUG_DISK(dsk, "ERROR(%d) "error, __LINE__, ##__VA_ARGS__)

#else
#define CASDSK_DEBUG_TRACE()
#define CASDSK_DEBUG_DISK_TRACE(dsk)
#define CASDSK_DEBUG_MSG(msg)
#define CASDSK_DEBUG_PARAM(format, ...)
#define CASDSK_DEBUG_DISK(dsk, format, ...)
#define CASDSK_DEBUG_ERROR(error, ...)
#define CASDSK_DEBUG_DISK_ERROR(dsk, error, ...)
#endif

#endif
