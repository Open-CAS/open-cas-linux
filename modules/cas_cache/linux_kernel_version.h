/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
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

#if LINUX_VERSION_CODE < KERNEL_VERSION(2, 6, 32)
	#error Unsupported Linux Kernel Version
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 19, 0)
	#define FILE_INODE(file) file->f_inode
#else
	#define FILE_INODE(file) file->f_dentry->d_inode
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 10, 76)
	#define DENTRY_ALIAS_HEAD(dentry) (dentry)->d_u.d_alias
	#define ALIAS_NODE_TO_DENTRY(alias) container_of(alias, struct dentry, d_u.d_alias)
#else
	#define DENTRY_ALIAS_HEAD(dentry) (dentry)->d_alias
	#define ALIAS_NODE_TO_DENTRY(alias) container_of(alias, struct dentry, d_alias)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 6, 0)
	#define ALIAS_NODE_TYPE struct hlist_node
	#define DENTRY_LIST_EMPTY(head) hlist_empty(head)
	#define INODE_FOR_EACH_DENTRY(pos, head) hlist_for_each(pos, head)
#else
	#define DENTRY_LIST_EMPTY(head) list_empty(head)
	#define ALIAS_NODE_TYPE struct list_head
	#define INODE_FOR_EACH_DENTRY(pos, head) list_for_each(pos, head)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 13, 0)
	#define BIO_OP_STATUS(bio) bio->bi_status
#else
	#define BIO_OP_STATUS(bio) bio->bi_error
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 13, 0)
#define WLTH_SUPPORT
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 3, 0)
	#define BIO_ENDIO(BIO, BYTES_DONE, ERROR) \
			({ BIO_OP_STATUS(BIO) = ERROR; bio_endio(BIO); })
#else
	#define BIO_ENDIO(BIO, BYTES_DONE, ERROR) bio_endio(BIO, ERROR)
#endif

#define REFER_BLOCK_CALLBACK(name) name##_callback
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 3, 0)
	#define DECLARE_BLOCK_CALLBACK(name, BIO, BYTES_DONE, ERROR) \
			void name##_callback(BIO, ERROR)
	#define BLOCK_CALLBACK_INIT(BIO) {; }
	#define BLOCK_CALLBACK_RETURN() { return; }
	#define BLOCK_CALLBACK_ERROR(BIO, ERROR) ERROR
#else
	#define DECLARE_BLOCK_CALLBACK(name, BIO, BYTES_DONE, ERROR) \
			void name##_callback(BIO)
	#define BLOCK_CALLBACK_INIT(BIO) {; }
	#define BLOCK_CALLBACK_RETURN() { return; }
	#define BLOCK_CALLBACK_ERROR(BIO, ERROR) BIO_OP_STATUS(BIO)
#endif

#if LINUX_VERSION_CODE > KERNEL_VERSION(2, 6, 37)
	#define OPEN_BDEV_EXCLUSIVE(PATH, FMODE, HOLDER) \
			blkdev_get_by_path(PATH, (FMODE_EXCL | FMODE), HOLDER)
	#define CLOSE_BDEV_EXCLUSIVE(BDEV, FMODE) \
			blkdev_put(BDEV, (FMODE_EXCL | FMODE))
#else
	#define OPEN_BDEV_EXCLUSIVE(PATH, FMODE, HOLDER) \
			open_bdev_exclusive(PATH, FMODE, HOLDER)
	#define CLOSE_BDEV_EXCLUSIVE(BDEV, FMODE) \
			close_bdev_exclusive(BDEV, FMODE)
#endif

#ifdef CAS_UBUNTU
	#define LOOKUP_BDEV(PATH) lookup_bdev(PATH, 0)
#else
	#define LOOKUP_BDEV(PATH) lookup_bdev(PATH)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 8, 0) || defined CAS_SLES12SP3
	#define BIO_OP_FLAGS_FORMAT "0x%016X"
	#define BIO_OP_FLAGS(bio) (bio)->bi_opf
#else
	#define BIO_OP_FLAGS_FORMAT "0x%016lX"
	#define BIO_OP_FLAGS(bio) (bio)->bi_rw
#endif

#if LINUX_VERSION_CODE <= KERNEL_VERSION(2, 6, 32)
	#define BIO_RW_FLAGS ((1U << BIO_RW_UNPLUG) | \
			(1U << BIO_RW_NOIDLE) | (1U << BIO_RW_SYNCIO))
	#define BIO_SET_RW_FLAGS(bio) BIO_OP_FLAGS((bio)) |= BIO_RW_FLAGS
#else
	#define BIO_RW_FLAGS 0
	#define BIO_SET_RW_FLAGS(bio)
#endif

#if defined RQF_SOFTBARRIER
	#define CHECK_BARRIER(bio) ((BIO_OP_FLAGS(bio) & RQF_SOFTBARRIER) != 0)
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(3, 0, 1)
	#define CHECK_BARRIER(bio) ((BIO_OP_FLAGS(bio) & REQ_SOFTBARRIER) != 0)
#else
	#define CHECK_BARRIER(bio) (bio_rw_flagged((bio), BIO_RW_BARRIER))
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 8, 0) || defined CAS_SLES12SP3
	#define RQ_DATA_DIR(rq) rq_data_dir(rq)
	#define RQ_DATA_DIR_WR WRITE
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(2, 6, 34)
	#define RQ_DATA_DIR(rq) rq_data_dir(rq)
	#define RQ_DATA_DIR_WR REQ_WRITE
#else
	#define RQ_DATA_DIR(rq) rq_data_dir(rq)
	#define RQ_DATA_DIR_WR WRITE
#endif

#if defined REQ_PREFLUSH
	#define CAS_REQ_FLUSH REQ_PREFLUSH
	#define CAS_FLUSH_SUPPORTED
#elif defined REQ_FLUSH
	#define CAS_REQ_FLUSH REQ_FLUSH
	#define CAS_FLUSH_SUPPORTED
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 6, 0) || defined CAS_SLES12SP3
#define CHECK_QUEUE_FLUSH(q) test_bit(QUEUE_FLAG_WC, &(q)->queue_flags)
#define CHECK_QUEUE_FUA(q) test_bit(QUEUE_FLAG_FUA, &(q)->queue_flags)

static inline void cas_set_queue_flush_fua(struct request_queue *q,
					  bool flush, bool fua)
{
	blk_queue_write_cache(q, flush, fua);
}

#else
#define CHECK_QUEUE_FLUSH(q) ((q)->flush_flags & CAS_REQ_FLUSH)
#define CHECK_QUEUE_FUA(q) ((q)->flush_flags & REQ_FUA)

static inline void cas_set_queue_flush_fua(struct request_queue *q,
					  bool flush, bool fua)
{
	unsigned int flags = 0;
	if (flush)
		flags |= CAS_REQ_FLUSH;
	if (fua)
		flags |= REQ_FUA;
	if (flags)
		blk_queue_flush(q, flags);
}
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(2, 6, 32)

	#ifdef WRITE_FLUSH
		#define RQ_IS_FLUSH(rq) ((rq)->cmd_flags & CAS_REQ_FLUSH)
		#ifdef BIO_FLUSH
			#define CAS_IS_WRITE_FLUSH(flags) ((flags) & BIO_FLUSH)
		#else
			#define CAS_IS_WRITE_FLUSH(flags) \
				((flags) & CAS_REQ_FLUSH)
		#endif

		#define OCF_WRITE_FLUSH WRITE_FLUSH
	#elif defined REQ_PREFLUSH
		#define RQ_IS_FLUSH(rq) ((rq)->cmd_flags & REQ_PREFLUSH)
		#define OCF_WRITE_FLUSH (REQ_OP_WRITE | REQ_PREFLUSH)
		#define CAS_IS_WRITE_FLUSH(flags) \
			(OCF_WRITE_FLUSH == ((flags) & OCF_WRITE_FLUSH))
	#else
		#define RQ_IS_FLUSH(rq) 0
		#define CAS_IS_WRITE_FLUSH(flags) \
			(WRITE_BARRIER == ((flags) & WRITE_BARRIER))
		#define OCF_WRITE_FLUSH WRITE_BARRIER
	#endif /* #ifdef WRITE_FLUSH */

	#ifdef WRITE_FLUSH_FUA
		#define OCF_WRITE_FLUSH_FUA WRITE_FLUSH_FUA
		#ifdef BIO_FUA
			#define CAS_IS_WRITE_FLUSH_FUA(flags) \
				((BIO_FUA | BIO_FLUSH) == \
				 ((flags) & (BIO_FUA | BIO_FLUSH)))
		#else
			#define CAS_IS_WRITE_FLUSH_FUA(flags) \
				((REQ_FUA | CAS_REQ_FLUSH) == \
				 ((flags) & (REQ_FUA | CAS_REQ_FLUSH)))
		#endif

	#elif defined REQ_PREFLUSH
			#define CAS_IS_WRITE_FLUSH_FUA(flags) \
				((REQ_PREFLUSH | REQ_FUA) == \
				((flags) & (REQ_PREFLUSH |REQ_FUA)))
			#define OCF_WRITE_FLUSH_FUA (REQ_PREFLUSH | REQ_FUA)
	#else
			#define CAS_IS_WRITE_FLUSH_FUA(flags) 0
			#define OCF_WRITE_FLUSH_FUA WRITE_BARRIER
	#endif /* #ifdef WRITE_FLUSH_FUA */

	#ifdef WRITE_FUA
		#ifdef BIO_FUA
			#define CAS_IS_WRITE_FUA(flags) ((flags) & BIO_FUA)
		#else
			#define CAS_IS_WRITE_FUA(flags) ((flags) & REQ_FUA)
		#endif
		#define OCF_WRITE_FUA WRITE_FUA
	#elif defined REQ_FUA
		#define CAS_IS_WRITE_FUA(flags) ((flags) & REQ_FUA)
		#define OCF_WRITE_FUA REQ_FUA
	#else
		#define CAS_IS_WRITE_FUA(flags) 0
		#define OCF_WRITE_FUA WRITE_BARRIER
	#endif /* #ifdef WRITE_FUA */

#endif /* #if LINUX_VERSION_CODE >= KERNEL_VERSION(2, 6, 32) */

#if LINUX_VERSION_CODE <= KERNEL_VERSION(3, 7, 9)
	#define DAEMONIZE(name, arg...) daemonize(name, ##arg)
#else
	#define DAEMONIZE(name, arg...) do { } while (0)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 16, 0)
	#define SET_QUEUE_CHUNK_SECTORS(queue, chunk_size) \
		queue->limits.chunk_sectors = chunk_size;
#else
	#define SET_QUEUE_CHUNK_SECTORS(queue, chunk_size) {; }
#endif

#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 14, 0)
	#define BIO_BISIZE(bio) bio->bi_size
	#define BIO_BIIDX(bio) bio->bi_idx
	#define BIO_BISECTOR(bio) bio->bi_sector
#else
	#define BIO_BISIZE(bio) bio->bi_iter.bi_size
	#define BIO_BISECTOR(bio) bio->bi_iter.bi_sector
	#define BIO_BIIDX(bio) bio->bi_iter.bi_idx
#endif

#ifdef CAS_SLES12SP3
	#define CAS_IS_DISCARD(bio) \
				(((BIO_OP_FLAGS(bio)) & REQ_OP_MASK) == REQ_OP_DISCARD)
	#define CAS_BIO_DISCARD \
				((REQ_OP_WRITE | REQ_OP_DISCARD))
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(4, 10, 0)
	#define CAS_IS_DISCARD(bio) \
				(bio_op(bio) == REQ_OP_DISCARD)
	#define CAS_BIO_DISCARD \
			   (REQ_OP_DISCARD)
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(4, 8, 0)
	#define CAS_IS_DISCARD(bio) \
		((BIO_OP_FLAGS(bio)) & REQ_OP_DISCARD)
	#define CAS_BIO_DISCARD \
		((REQ_OP_WRITE | REQ_OP_DISCARD))
#elif LINUX_VERSION_CODE > KERNEL_VERSION(2, 6, 32)
	#define CAS_IS_DISCARD(bio) ((BIO_OP_FLAGS(bio)) & REQ_DISCARD)
	#define CAS_BIO_DISCARD (REQ_WRITE | REQ_DISCARD)
#else
	#define CAS_IS_DISCARD(bio) ((BIO_OP_FLAGS(bio)) & (1 << BIO_RW_DISCARD))
	#define CAS_BIO_DISCARD ((1 << BIO_RW) | (1 << BIO_RW_DISCARD))
#endif

#include <linux/mm.h>

#if LINUX_VERSION_CODE > KERNEL_VERSION(2, 6, 32)
#include <uapi/asm-generic/mman-common.h>
static inline unsigned long cas_vm_mmap(struct file *file,
		unsigned long addr, unsigned long len)
{
	return vm_mmap(file, addr, len, PROT_READ | PROT_WRITE,
			MAP_ANONYMOUS | MAP_PRIVATE, 0);
}

static inline int cas_vm_munmap(unsigned long start, size_t len)
{
	return vm_munmap(start, len);
}
#else
#include <asm-generic/mman-common.h>
static inline unsigned long cas_vm_mmap(struct file *file,
		unsigned long addr, unsigned long len)
{
	return do_mmap_pgoff(file, addr, len, PROT_READ | PROT_WRITE,
			MAP_ANONYMOUS | MAP_PRIVATE, 0);
}

static inline int cas_vm_munmap(unsigned long start, size_t len)
{
	return do_munmap(current->mm, start, len);
}
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

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 14, 0)
	#define SEGMENT_BVEC(vec) (&(vec))
#else
	#define SEGMENT_BVEC(vec) (vec)
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

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0) || defined CAS_SLES12SP3
static inline blk_qc_t cas_submit_bio(int rw, struct bio *bio)
{
	BIO_OP_FLAGS(bio) |= rw;
	return submit_bio(bio);
}
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
static inline blk_qc_t cas_submit_bio(int rw, struct bio *bio)
{
	return submit_bio(rw, bio);
}
#else
static inline void cas_submit_bio(int rw, struct bio *bio)
{
	submit_bio(rw, bio);
}
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 11, 0)
#define cas_blk_rq_set_block_pc(rq) {}
#else
#define cas_blk_rq_set_block_pc(rq) blk_rq_set_block_pc(rq)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 13, 0)
#define cas_blk_queue_bounce(q, bounce_bio) ({})
#else
#define cas_blk_queue_bounce(q, bounce_bio) blk_queue_bounce(q, bounce_bio)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 14, 11)
#define cas_blk_rq_append_bio(rq, bounce_bio) blk_rq_append_bio(rq, &bounce_bio)
#else
#define cas_blk_rq_append_bio(rq, bounce_bio) blk_rq_append_bio(rq, bounce_bio)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 8, 0) || defined CAS_SLES12SP3
static inline struct request *cas_blk_make_request(struct request_queue *q,
		struct bio *bio, gfp_t gfp_mask)
{
	struct request *rq = blk_get_request(q, bio_data_dir(bio), gfp_mask);

	if (IS_ERR(rq))
		return rq;

	cas_blk_rq_set_block_pc(rq);
	rq->q = q;

	for_each_bio(bio) {
		struct bio *bounce_bio = bio;
		int ret;

		cas_blk_queue_bounce(q, &bounce_bio);
		ret = cas_blk_rq_append_bio(rq, bounce_bio);
		if (unlikely(ret)) {
			blk_put_request(rq);
			return ERR_PTR(ret);
		}
	}

	return rq;
}
#else
static inline struct request *cas_blk_make_request(struct request_queue *q,
		struct bio *bio, gfp_t gfp_mask)
{
	return blk_make_request(q, bio, gfp_mask);
}
#endif

#ifdef CAS_RHEL_73
static inline void cas_copy_queue_limits(struct request_queue *exp_q,
		struct request_queue *cache_q, struct request_queue *core_q)
{
	struct queue_limits_aux *l_aux = exp_q->limits.limits_aux;

	exp_q->limits = cache_q->limits;
	exp_q->limits.limits_aux = l_aux;
	if (exp_q->limits.limits_aux && cache_q->limits.limits_aux)
		*exp_q->limits.limits_aux = *cache_q->limits.limits_aux;

	exp_q->limits.max_sectors = core_q->limits.max_sectors;
	exp_q->limits.max_hw_sectors = core_q->limits.max_hw_sectors;
	exp_q->limits.max_segments = core_q->limits.max_segments;
	exp_q->limits.max_write_same_sectors = 0;

	/*
	 * Workaround for RHEL/CentOS 7.3 bug in kernel.
	 * Merging implementation on blk-mq does not respec virt boundary
	 * restriction and front merges bios with non-zero offsets.
	 * This leads to request with gaps between bios and in consequence
	 * triggers BUG_ON() in nvme driver or silently corrupts data.
	 * To prevent this, disable merging on cache queue if there are
	 * requirements regarding virt boundary (marking bios with REQ_NOMERGE
	 * does not solve this problem).
	 */
	if (queue_virt_boundary(cache_q))
		queue_flag_set(QUEUE_FLAG_NOMERGES, cache_q);

}
#else
static inline void cas_copy_queue_limits(struct request_queue *exp_q,
		struct request_queue *cache_q, struct request_queue *core_q)
{
	exp_q->limits = cache_q->limits;

	exp_q->limits.max_sectors = core_q->limits.max_sectors;
	exp_q->limits.max_hw_sectors = core_q->limits.max_hw_sectors;
	exp_q->limits.max_segments = core_q->limits.max_segments;
#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 7, 0) || defined CAS_SLES12SP3
	exp_q->limits.max_write_same_sectors = 0;
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 10, 0) || defined CAS_SLES12SP3
	exp_q->limits.max_write_zeroes_sectors = 0;
#endif
}
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3,8,0)
	#define CAS_GARBAGE_COLLECTOR
#endif

/* rate-limited printk */
#define CAS_PRINT_RL(...) \
	if (printk_ratelimit()) \
		printk(__VA_ARGS__)

#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 19, 0)
static inline void cas_generic_start_io_acct(struct request_queue *q,
		int rw, unsigned long sectors, struct hd_struct *part)
{
	int cpu = part_stat_lock();

	CAS_PART_ROUND_STATS(q, cpu, part);
	part_stat_inc(cpu, part, ios[rw]);
	part_stat_add(cpu, part, sectors[rw], sectors);
	CAS_PART_INC_IN_FLIGHT(q, part, rw);

	part_stat_unlock();
}

static inline void cas_generic_end_io_acct(struct request_queue *q,
		int rw, struct hd_struct *part, unsigned long start_time)
{
	unsigned long duration = jiffies - start_time;
	int cpu = part_stat_lock();

	part_stat_add(cpu, part, ticks[rw], duration);
	CAS_PART_ROUND_STATS(q, cpu, part);
	CAS_PART_DEC_IN_FLIGHT(q, part, rw);

	part_stat_unlock();
}
#elif LINUX_VERSION_CODE < KERNEL_VERSION(4, 14, 0)
static inline void cas_generic_start_io_acct(struct request_queue *q,
		int rw, unsigned long sectors, struct hd_struct *part)
{
	generic_start_io_acct(rw, sectors, part);
}

static inline void cas_generic_end_io_acct(struct request_queue *q,
		int rw, struct hd_struct *part, unsigned long start_time)
{
	generic_end_io_acct(rw, part, start_time);
}
#else
static inline void cas_generic_start_io_acct(struct request_queue *q,
		int rw, unsigned long sectors, struct hd_struct *part)
{
	generic_start_io_acct(q, rw, sectors, part);
}

static inline void cas_generic_end_io_acct(struct request_queue *q,
		int rw, struct hd_struct *part, unsigned long start_time)
{
	generic_end_io_acct(q, rw, part, start_time);
}
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 14, 0)
static inline unsigned long cas_global_zone_page_state(enum zone_stat_item item)
{
	return global_zone_page_state(item);
}
#define CAS_BIO_SET_DEV(bio, bdev) bio_set_dev(bio, bdev)
#define CAS_BIO_GET_DEV(bio) bio->bi_disk
#else
static inline unsigned long cas_global_zone_page_state(enum zone_stat_item item)
{
	return global_page_state(item);
}
#define CAS_BIO_SET_DEV(bio, bdev) bio->bi_bdev = bdev
#define CAS_BIO_GET_DEV(bio) bio->bi_bdev->bd_disk
#endif

#if LINUX_VERSION_CODE < KERNEL_VERSION(2, 6, 33)
	#define CAS_RATELIMIT(state, func_name) __ratelimit(state)
#else
	#define CAS_RATELIMIT(state, func_name) ___ratelimit(state, func_name)
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 19, 0)
static inline struct bio *cas_bio_clone(struct bio *bio, gfp_t gfp_mask)
{
	return bio_clone_fast(bio, gfp_mask, NULL);
}
#elif LINUX_VERSION_CODE >= KERNEL_VERSION(4, 13, 0)
static inline struct bio *cas_bio_clone(struct bio *bio, gfp_t gfp_mask)
{
	return bio_clone_kmalloc(bio, gfp_mask);
}
	#define CAS_BLK_STATUS_T blk_status_t
#else
static inline struct bio *cas_bio_clone(struct bio *bio, gfp_t gfp_mask)
{
	return bio_clone(bio, gfp_mask);
}
	#define CAS_BLK_STATUS_T int
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 11, 0)
static inline int is_rq_type_fs(struct request *rq)
{
	switch (req_op(rq)){
	case REQ_OP_READ:
	case REQ_OP_WRITE:
	case REQ_OP_FLUSH:
	case REQ_OP_DISCARD:
		return true;
	default:
		return false;
	}
}
#else
static inline int is_rq_type_fs(struct request *rq)
{
	return rq->cmd_type == REQ_TYPE_FS;
}
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 12, 0)
	#define CAS_SET_DISCARD_ZEROES_DATA(queue_limits, val) ({})
#else
	#define CAS_SET_DISCARD_ZEROES_DATA(queue_limits, val) \
			queue_limits.discard_zeroes_data = val
#endif

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 17, 0)
	#define cas_queue_flag_set_unlocked(flag, request_queue) \
			blk_queue_flag_set(flag, request_queue)
#else
	#define cas_queue_flag_set_unlocked(flag, request_queue) \
			queue_flag_set_unlocked(flag, request_queue)
#endif

#endif /* #ifndef __LINUX_KERNEL_VERSION_H__ */
