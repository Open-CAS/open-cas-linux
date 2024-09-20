/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
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
#include "exp_obj.h"

#include "generated_defines.h"

#ifdef CONFIG_SLAB
#include <linux/slab_def.h>
#endif

#ifndef SHRT_MIN
	#define SHRT_MIN ((s16)-32768)
#endif

#ifndef SHRT_MAX
	#define SHRT_MAX ((s16)32767)
#endif

#define ENOTSUP ENOTSUPP

/* rate-limited printk */
#define CAS_PRINT_RL(...) \
	if (printk_ratelimit()) \
		printk(__VA_ARGS__)

#endif /* #ifndef __LINUX_KERNEL_VERSION_H__ */
