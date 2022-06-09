/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __LINUX_KERNEL_VERSION_H__
#define __LINUX_KERNEL_VERSION_H__

/* Libraries. */
#include <linux/types.h>
#include <linux/module.h>
#include <linux/list.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/errno.h>
#include <linux/vmalloc.h>
#include <linux/uaccess.h>
#include <linux/kthread.h>
#include <linux/spinlock.h>
#include <linux/bio.h>
#include <linux/fs.h>
#include <linux/stat.h>
#include <linux/genhd.h>
#include <linux/blkdev.h>
#include <linux/version.h>
#include <linux/workqueue.h>
#include <linux/cpumask.h>
#include <linux/smp.h>
#include <linux/ioctl.h>
#include <linux/delay.h>
#include <linux/sort.h>
#include <linux/swap.h>
#include <linux/thread_info.h>
#include <asm-generic/ioctl.h>
#include <linux/bitops.h>
#include <linux/crc16.h>
#include <linux/crc32.h>
#include <linux/nmi.h>
#include <linux/ratelimit.h>
#include <linux/mm.h>
#include <linux/blk-mq.h>
#include <linux/ktime.h>
#include "../cas_disk/exp_obj.h"

#include "generated_defines.h"

#ifdef CONFIG_SLAB
#include <linux/slab_def.h>
#endif

#if LINUX_VERSION_CODE > KERNEL_VERSION(3, 0, 0)
	#include <generated/utsrelease.h>
	#ifdef UTS_UBUNTU_RELEASE_ABI
		#define CAS_UBUNTU
	#endif
#endif

/*
 * For 8KB process kernel stack check if request is not continous and
 * submit each bio as separate request. This prevent nvme driver from
 * splitting requests.
 * For large requests, nvme splitting causes stack overrun.
 */
#if THREAD_SIZE <= 8192
	#define RQ_CHECK_CONTINOUS
#endif

#ifndef SHRT_MIN
	#define SHRT_MIN ((s16)-32768)
#endif

#ifndef SHRT_MAX
	#define SHRT_MAX ((s16)32767)
#endif

#define ENOTSUP ENOTSUPP

#ifdef RHEL_RELEASE_VERSION
	#if RHEL_RELEASE_CODE == RHEL_RELEASE_VERSION(7, 3)
		#define CAS_RHEL_73
	#endif
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3,8,0)
	#define CAS_GARBAGE_COLLECTOR
#endif

/* rate-limited printk */
#define CAS_PRINT_RL(...) \
	if (printk_ratelimit()) \
		printk(__VA_ARGS__)

#endif /* #ifndef __LINUX_KERNEL_VERSION_H__ */
