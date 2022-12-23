/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/


#ifndef __OCF_ENV_H__
#define __OCF_ENV_H__

#include "linux_kernel_version.h"
#include "utils/utils_gc.h"
#include "ocf/ocf_err.h"
#include "utils/utils_mpool.h"

/* linux sector 512-bytes */
#define ENV_SECTOR_SHIFT	9

/* *** MEMORY MANAGEMENT *** */

#define ENV_MEM_NORMAL	GFP_KERNEL
#define ENV_MEM_NOIO	GFP_NOIO

static inline uint64_t env_get_free_memory(void)
{
	return cas_global_zone_page_state(NR_FREE_PAGES) << PAGE_SHIFT;
}

static inline void *env_malloc(size_t size, int flags)
{
	return kmalloc(size, flags);
}

static inline void *env_zalloc(size_t size, int flags)
{
	return kzalloc(size, flags);
}

static inline void env_free(const void *ptr)
{
	kfree(ptr);
}

static inline void *env_vmalloc_flags(size_t size, int flags)
{
	return cas_vmalloc(size, flags | __GFP_HIGHMEM);
}

static inline void *env_vzalloc_flags(size_t size, int flags)
{
	return env_vmalloc_flags(size, flags | __GFP_ZERO);
}

static inline void *env_vmalloc(size_t size)
{
	return env_vmalloc_flags(size, GFP_KERNEL);
}

static inline void *env_vzalloc(size_t size)
{
	return env_vzalloc_flags(size, GFP_KERNEL);
}

static inline void env_vfree(const void *ptr)
{
	cas_vfree(ptr);
}

static inline void *env_secure_alloc(size_t size)
{
	return env_vmalloc(size);
}

static inline void env_secure_free(const void *ptr, size_t size)
{
	env_vfree(ptr);
}

/* *** ALLOCATOR *** */

typedef struct _env_allocator env_allocator;

env_allocator *env_allocator_create_extended(uint32_t size, const char *name,
	int rpool_limit);

env_allocator *env_allocator_create(uint32_t size, const char *name, bool zero);

void env_allocator_destroy(env_allocator *allocator);

void *env_allocator_new(env_allocator *allocator);

void env_allocator_del(env_allocator *allocator, void *item);

uint32_t env_allocator_item_count(env_allocator *allocator);

/* *** MUTEX *** */

typedef struct mutex env_mutex;

static inline int env_mutex_init(env_mutex *mutex)
{
	mutex_init(mutex);
	return 0;
}

static inline void env_mutex_lock(env_mutex *mutex)
{
	mutex_lock(mutex);
}

static inline int env_mutex_lock_interruptible(env_mutex *mutex)
{
	return mutex_lock_interruptible(mutex) ? -OCF_ERR_INTR : 0;
}

static inline int env_mutex_trylock(env_mutex *mutex)
{
	return mutex_trylock(mutex) ? 0 : -OCF_ERR_NO_LOCK;
}

static inline void env_mutex_unlock(env_mutex *mutex)
{
	mutex_unlock(mutex);
}

static inline int env_mutex_is_locked(env_mutex *mutex)
{
	return mutex_is_locked(mutex);
}

static inline void env_mutex_destroy(env_mutex *mutex)
{
}

/* *** RECURSIVE MUTEX *** */

typedef struct {
	struct mutex mutex;
	uint32_t count;
	struct task_struct *holder;
} env_rmutex;

static inline int env_rmutex_init(env_rmutex *rmutex)
{
	mutex_init(&rmutex->mutex);
	rmutex->count = 0;
	rmutex->holder = NULL;
	return 0;
}

static inline void env_rmutex_lock(env_rmutex *rmutex)
{
	if (current == rmutex->holder) {
		rmutex->count++;
		return;
	}

	mutex_lock(&rmutex->mutex);
	rmutex->holder = current;
	rmutex->count++;
}

static inline int env_rmutex_lock_interruptible(env_rmutex *rmutex)
{
	int result = 0;
	if (current == rmutex->holder) {
		rmutex->count++;
		return 0;
	}

	result = mutex_lock_interruptible(&rmutex->mutex);
	if (result) {
		/* No lock */
		return -OCF_ERR_INTR;
	}

	rmutex->holder = current;
	rmutex->count++;

	return 0;
}

static inline int env_rmutex_trylock(env_rmutex *rmutex)
{
	if (current == rmutex->holder) {
		rmutex->count++;
		return 0;
	}

	if (mutex_trylock(&rmutex->mutex)) {
		/* No lock */
		return -OCF_ERR_NO_LOCK;
	}

	rmutex->holder = current;
	rmutex->count++;

	return 0;
}

static inline void env_rmutex_unlock(env_rmutex *rmutex)
{
	BUG_ON(current != rmutex->holder);

	if (--rmutex->count) {
		return;
	}

	rmutex->holder = NULL;
	mutex_unlock(&rmutex->mutex);
}

static inline int env_rmutex_is_locked(env_rmutex *rmutex)
{
	return mutex_is_locked(&rmutex->mutex);
}

static inline void env_rmutex_destroy(env_rmutex *rmutex)
{
}

/* *** RW SEMAPHORE *** */

typedef struct rw_semaphore env_rwsem;

static inline int env_rwsem_init(env_rwsem *s)
{
	init_rwsem(s);
	return 0;
}

static inline void env_rwsem_up_read(env_rwsem *s)
{
	up_read(s);
}

static inline void env_rwsem_down_read(env_rwsem *s)
{
	down_read(s);
}

static inline int env_rwsem_down_read_trylock(env_rwsem *s)
{
	return down_read_trylock(s) ? 0 : -OCF_ERR_NO_LOCK;
}

static inline void env_rwsem_up_write(env_rwsem *s)
{
	up_write(s);
}

static inline void env_rwsem_down_write(env_rwsem *s)
{
	down_write(s);
}

static inline int env_rwsem_down_write_trylock(env_rwsem *s)
{
	return down_write_trylock(s) ? 0 : -OCF_ERR_NO_LOCK;
}

static inline int env_rwsem_is_locked(env_rwsem *s)
{
	return rwsem_is_locked(s);
}

static inline int env_rwsem_destroy(env_rwsem *s)
{
	return 0;
}

/* *** COMPLETION *** */

typedef struct completion env_completion;

static inline void env_completion_init(env_completion *completion)
{
	init_completion(completion);
}

static inline void env_completion_wait(env_completion *completion)
{
	wait_for_completion(completion);
}

static inline void env_completion_complete(env_completion *completion)
{
	complete(completion);
}

static inline void env_completion_destroy(env_completion *completion)
{
}

/* *** ATOMIC VARIABLES *** */

typedef atomic_t env_atomic;
typedef atomic64_t env_atomic64;

static inline int env_atomic_read(const env_atomic *a)
{
	return atomic_read(a);
}

static inline void env_atomic_set(env_atomic *a, int i)
{
	atomic_set(a, i);
}

static inline void env_atomic_add(int i, env_atomic *a)
{
	atomic_add(i, a);
}

static inline void env_atomic_sub(int i, env_atomic *a)
{
	atomic_sub(i, a);
}

static inline bool env_atomic_sub_and_test(int i, env_atomic *a)
{
	return atomic_sub_and_test(i, a);
}

static inline void env_atomic_inc(env_atomic *a)
{
	atomic_inc(a);
}

static inline void env_atomic_dec(env_atomic *a)
{
	atomic_dec(a);
}

static inline bool env_atomic_dec_and_test(env_atomic *a)
{
	return atomic_dec_and_test(a);
}

static inline bool env_atomic_inc_and_test(env_atomic *a)
{
	return atomic_inc_and_test(a);
}

static inline int env_atomic_add_return(int i, env_atomic *a)
{
	return atomic_add_return(i, a);
}

static inline int env_atomic_sub_return(int i, env_atomic *a)
{
	return atomic_sub_return(i, a);
}

static inline int env_atomic_inc_return(env_atomic *a)
{
	return atomic_inc_return(a);
}

static inline int env_atomic_dec_return(env_atomic *a)
{
	return atomic_dec_return(a);
}

static inline int env_atomic_cmpxchg(env_atomic *a, int old, int new_value)
{
	return atomic_cmpxchg(a, old, new_value);
}

static inline int env_atomic_add_unless(env_atomic *a, int i, int u)
{
	return atomic_add_unless(a, i, u);
}

static inline u64 env_atomic64_read(const env_atomic64 *a)
{
	return atomic64_read(a);
}

static inline void env_atomic64_set(env_atomic64 *a, u64 i)
{
	atomic64_set(a, i);
}

static inline void env_atomic64_add(u64 i, env_atomic64 *a)
{
	atomic64_add(i, a);
}

static inline void env_atomic64_sub(u64 i, env_atomic64 *a)
{
	atomic64_sub(i, a);
}

static inline void env_atomic64_inc(env_atomic64 *a)
{
	atomic64_inc(a);
}

static inline void env_atomic64_dec(env_atomic64 *a)
{
	atomic64_dec(a);
}

static inline u64 env_atomic64_inc_return(env_atomic64 *a)
{
	return atomic64_inc_return(a);
}

static inline u64 env_atomic64_cmpxchg(atomic64_t *a, u64 old, u64 new)
{
	return atomic64_cmpxchg(a, old, new);
}

/* *** SPIN LOCKS *** */

typedef spinlock_t env_spinlock;

static inline int env_spinlock_init(env_spinlock *l)
{
	spin_lock_init(l);
	return 0;
}

static inline void env_spinlock_lock(env_spinlock *l)
{
	spin_lock(l);
}

static inline int env_spinlock_trylock(env_spinlock *l)
{
	return spin_trylock(l) ? 0 : -OCF_ERR_NO_LOCK;
}

static inline void env_spinlock_unlock(env_spinlock *l)
{
	spin_unlock(l);
}

static inline void env_spinlock_lock_irq(env_spinlock *l)
{
	spin_lock_irq(l);
}

static inline void env_spinlock_unlock_irq(env_spinlock *l)
{
	spin_unlock_irq(l);
}

static inline void env_spinlock_destroy(env_spinlock *l)
{
}

#define env_spinlock_lock_irqsave(l, flags) \
		spin_lock_irqsave((l), (flags))

#define env_spinlock_unlock_irqrestore(l, flags) \
		spin_unlock_irqrestore((l), (flags))

/* *** RW LOCKS *** */

typedef rwlock_t env_rwlock;

static inline void env_rwlock_init(env_rwlock *l)
{
	rwlock_init(l);
}

static inline void env_rwlock_read_lock(env_rwlock *l)
{
	read_lock(l);
}

static inline void env_rwlock_read_unlock(env_rwlock *l)
{
	read_unlock(l);
}

static inline void env_rwlock_write_lock(env_rwlock *l)
{
	write_lock(l);
}

static inline void env_rwlock_write_unlock(env_rwlock *l)
{
	write_unlock(l);
}

static inline void env_rwlock_destroy(env_rwlock *l)
{
}

/* *** WAITQUEUE *** */

typedef wait_queue_head_t env_waitqueue;

static inline void env_waitqueue_init(env_waitqueue *w)
{
	init_waitqueue_head(w);
}

static inline void env_waitqueue_wake_up(env_waitqueue *w)
{
	wake_up(w);
}

#define env_waitqueue_wait(w, condition) \
		wait_event_interruptible((w), (condition))

/* *** SCHEDULING *** */
static inline void env_cond_resched(void)
{
	cond_resched();
}

static inline int env_in_interrupt(void)
{
	return in_interrupt();
}

/* *** TIME *** */
static inline uint64_t env_get_tick_count(void)
{
	struct timespec64 ts;
	CAS_GET_CURRENT_TIME(&ts);
	return ts.tv_sec * 1000000000UL + ts.tv_nsec;
}

static inline uint64_t env_ticks_to_nsecs(uint64_t j)
{
	return j;
}

static inline uint64_t env_ticks_to_usecs(uint64_t j)
{
	return j / 1000UL;
}

static inline uint64_t env_ticks_to_msecs(uint64_t j)
{
	return j / 1000000UL;
}

static inline uint64_t env_ticks_to_secs(uint64_t j)
{
	return j / 1000000000UL;
}

static inline uint64_t env_secs_to_ticks(uint64_t j)
{
	return j * 1000000000UL;
}

static inline bool env_time_after(uint64_t a, uint64_t b)
{
	return time_after64(a,b);
}

static inline void env_msleep(uint64_t n)
{
	msleep(n);
}

/* *** BIT OPERATIONS *** */

static inline void env_bit_set(int nr, volatile void *addr)
{
	set_bit(nr, addr);
}

static inline void env_bit_clear(int nr, volatile void *addr)
{
	clear_bit(nr, addr);
}

static inline int env_bit_test(int nr, const void *addr)
{
	return test_bit(nr, addr);
}

/* *** STRING OPERATIONS *** */


#define env_memset(dest, dmax, val) ({ \
		memset(dest, val, dmax); \
		0; \
	})
#define env_memcpy(dest, dmax, src, slen) ({ \
		memcpy(dest, src, min_t(int, dmax, slen)); \
		0; \
	})
#define env_memcmp(s1, s1max, s2, s2max, diff) ({ \
		*diff = memcmp(s1, s2, min_t(int, s1max, s2max)); \
		0; \
	})
#define env_strdup kstrdup
#define env_strnlen(s, smax) strnlen(s, smax)
#define env_strncmp(s1, slen1, s2, slen2) strncmp(s1, s2, \
					min_t(size_t, slen1, slen2))
#define env_strncpy(dest, dmax, src, slen) ({ \
		strlcpy(dest, src, min_t(int, dmax, slen)); \
		0; \
	})

/* *** SORTING *** */

void env_sort(void *base, size_t num, size_t size,
	int (*cmp_fn)(const void *, const void *),
	void (*swap_fn)(void *, void *, int size));

/* *** CRC *** */

static inline uint32_t env_crc32(uint32_t crc, uint8_t const *data, size_t len)
{
	return crc32(crc, data, len);
}

/* *** LOGGING *** */

#define ENV_PRIu64 "llu"
#define ENV_PRId64 "lld"

#define ENV_WARN(cond, fmt...)		WARN(cond, fmt)
#define ENV_WARN_ON(cond)		WARN_ON(cond)

#define ENV_BUG()			BUG()
#define ENV_BUG_ON(cond)		BUG_ON(cond)
#define ENV_BUILD_BUG_ON(cond)		BUILD_BUG_ON(cond)


/* *** EXECUTION COTNEXT *** */
static inline unsigned env_get_execution_context(void)
{
	return get_cpu();
}

static inline void env_put_execution_context(unsigned ctx)
{
	put_cpu();
}

static inline unsigned env_get_execution_context_count(void)
{
	return num_online_cpus();
}

#endif /* __OCF_ENV_H__ */
