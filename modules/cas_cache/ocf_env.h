/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/


#ifndef __OCF_ENV_H__
#define __OCF_ENV_H__

#include "linux_kernel_version.h"
#include "utils/utils_gc.h"
#include "ocf/ocf_err.h"
#include "utils/utils_mpool.h"

/* linux sector 512-bytes */
#define ENV_SECTOR_SHIFT	9

/** @addtogroup MEMORY_MANAGEMENT
 * definitions for ENV_MEM_* macros - values for memory operations
 * @{
 */

#define ENV_MEM_NORMAL	GFP_KERNEL
#define ENV_MEM_NOIO	GFP_NOIO

/**
 * @brief wrapper for function which returns system's free memory
 * @retval unsigned long
 */
static inline uint64_t env_get_free_memory(void)
{
	return cas_global_zone_page_state(NR_FREE_PAGES) << PAGE_SHIFT;
}

/**
 * @brief wrapper for kmalloc
 * @param size bytes of memory to be allocated
 * @param flags the type of memory to be allocated
 * @retval void *
 */
static inline void *env_malloc(size_t size, int flags)
{
	return kmalloc(size, flags);
}

/**
 * @brief wrapper for kzalloc
 * @param size bytes of memory to be allocated and zeroed
 * @param flags the type of memory to be allocated
 * @retval void *
 */
static inline void *env_zalloc(size_t size, int flags)
{
	return kzalloc(size, flags);
}

/**
 * @brief wrapper for kfree
 * @param ptr pointer to memory to be freed
 */
static inline void env_free(const void *ptr)
{
	kfree(ptr);
}

/**
 * @brief wrapper for __vmalloc with __GFP_HIGHMEM and PAGE_KERNEL flags
 * @param size bytes of memory to be allocated
 * @param flags the type of memory to be allocated
 * @retval void *
 */
static inline void *env_vmalloc_flags(size_t size, int flags)
{
	return cas_vmalloc(size, flags | __GFP_HIGHMEM);
}

/**
 * @brief wrapper for env_vmalloc_flags with __GFP_ZERO flag
 * @param size bytes of memory to be allocated
 * @param flags the type of memory to be allocated
 * @retval void *
 */
static inline void *env_vzalloc_flags(size_t size, int flags)
{
	return env_vmalloc_flags(size, flags | __GFP_ZERO);
}

/**
 * @brief wrapper for env_vmalloc_flags with GFP_KERNEL flag
 * @param size bytes of memory to be allocated
 * @retval void *
 */
static inline void *env_vmalloc(size_t size)
{
	return env_vmalloc_flags(size, GFP_KERNEL);
}

/**
 * @brief wrapper for env_vzalloc_flags with GFP_KERNEL flag
 * @param size bytes of memory to be allocated
 * @retval void *
 */
static inline void *env_vzalloc(size_t size)
{
	return env_vzalloc_flags(size, GFP_KERNEL);
}

/**
 * @brief wrapper for cas_vfree
 * @param ptr pointer to memory to be freed
 */
static inline void env_vfree(const void *ptr)
{
	cas_vfree(ptr);
}

/**
 * @brief wrapper for vmalloc
 * @param size bytes of memory to be allocated
 * @retval void *
 */
static inline void *env_secure_alloc(size_t size)
{
	return env_vmalloc(size);
}

/**
 * @brief wrapper for env_vfree
 * @param ptr pointer to memory to be freed
 */
static inline void env_secure_free(const void *ptr, size_t size)
{
	env_vfree(ptr);
}
/** @} */

/** @addtogroup ALLOCATOR
 * @{
 */

/**
 * @struct env_allocator ocf_env.h "modules/cac_cache/ocf_env.h"
 * @brief _env_allocator struct wrapper
 * @details contains:
 * <tt>char *name</tt> - memory pool ID unique name 
 * <tt>uint32_t item_size</tt> - size of specific item of memory pool
 * <tt>struct kmem_cache *kmem_cache</tt> - OS handle to memory pool
 * <tt>env_atomic count</tt> - number of currently allocated items in pool
 * <tt>struct cas_reserve_pool *rpool</tt> - reserved memory pool
 */
typedef struct _env_allocator env_allocator;

/**
 * @brief creates new env_allocator struct
 * @details tries to allocate zeroed memory, adds size of specific item
 * formats name, initilizes kernel memory cache;
 * if not succeeded call destroy on initialized allocator
 * @param size bytes of memory to be allocated
 * @param name pointer to space with unique name
 * @param rpool_limit reserve pool handler per cpu limit
 */
env_allocator *env_allocator_create_extended(uint32_t size, const char *name,
	int rpool_limit);

/**
 * @brief wrapper for env_allocator_create_extended with max limit of reverse
 * pool handler
 * @details tries to allocate zeroed memory, adds size of specific item
 * formats name, initilizes kernel memory cache;
 * if not succeeded call destroy on initialized allocator
 * @param size bytes of memory to be allocated
 * @param name pointer to space with unique name
 */
env_allocator *env_allocator_create(uint32_t size, const char *name);

/**
 * @brief destroys env_allocator struct and frees memory blocks 
 * reserved by deleted allocator and its name
 * @param allocator pointer to env_allocator struct to be destroyed
 * @warning cleanup problem
 */
void env_allocator_destroy(env_allocator *allocator);

/**
 * @brief creates new allocator's item and increments atomic counter
 * @param allocator pointer to allocator to which item should be added
 * @retval address to array where data of currently allocated item is stored
 */
void *env_allocator_new(env_allocator *allocator);

/**
 * @brief deletes allocator's item, decrements atomic counter
 * and frees memory block reserved by deleted item
 * @param allocator pointer to allocator from which item should be removed
 * @param item pointer to item which should be removed
 */
void env_allocator_del(env_allocator *allocator, void *item);

/**
 * @brief read items counter in allocator
 * @param allocator pointer to allocator from which counter should be read
 */
uint32_t env_allocator_item_count(env_allocator *allocator);
/** @} */

/** @addtogroup MUTEX
 * @{
 */

/**
 * @struct env_mutex ocf_env.h "modules/cac_cache/ocf_env.h"
 * @brief mutex struct wrapper
 * @details contains:
 * <tt>atomic_long_t owner</tt> - mutex owner 
 * <tt>spinlock_t wait_lock</tt> - wait lock
 * <tt>struct list_head wait_list</tt> - list of wait locks
 */
typedef struct mutex env_mutex;

/**
 * @brief initiates env_mutex
 * @param mutex pointer to env_mutex which should be initiated
 * @retval 0
 */
static inline int env_mutex_init(env_mutex *mutex)
{
	mutex_init(mutex);
	return 0;
}

/**
 * @brief locks env_mutex
 * @param mutex pointer to env_mutex which should be locked
 */
static inline void env_mutex_lock(env_mutex *mutex)
{
	mutex_lock(mutex);
}

/**
 * @brief locks env_mutex, operation can be interrupted
 * @param mutex pointer to env_mutex which should be locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_INTR if interrupted
 */
static inline int env_mutex_lock_interruptible(env_mutex *mutex)
{
	return mutex_lock_interruptible(mutex) ? -OCF_ERR_INTR : 0;
}

/**
 * @brief tries to lock env_mutex
 * @param mutex pointer to env_mutex which should be locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_NO_LOCK if failed
 */
static inline int env_mutex_trylock(env_mutex *mutex)
{
	return mutex_trylock(mutex) ? 0 : -OCF_ERR_NO_LOCK;
}

/**
 * @brief unlocks env_mutex
 * @param mutex pointer to env_mutex which should be unlocked
 */
static inline void env_mutex_unlock(env_mutex *mutex)
{
	mutex_unlock(mutex);
}

/**
 * @brief checks if env_mutex is locked
 * @param mutex pointer to env_mutex which should be checked
 */
static inline int env_mutex_is_locked(env_mutex *mutex)
{
	return mutex_is_locked(mutex);
}

static inline void env_mutex_destroy(env_mutex *mutex)
{
}
/** @} */

/** @addtogroup RECURSIVE MUTEX
 * @{
 */

/**
 * @struct env_rmutex ocf_env.h "modules/cac_cache/ocf_env.h"
 * @brief env_mutex struct wrapper
 * @details contains:
 * <tt>struct mutex mutex</tt> - mutex
 * <tt>atomic_t count</tt> - counter of mutexes
 * <tt>struct task_struct holder</tt> - holder for rmutex's task
 */
typedef struct {
	struct mutex mutex;
	atomic_t count;
	struct task_struct *holder;
} env_rmutex;

/**
 * @brief initiates mutex inside env_rmutex struct and other fields
 * @param rmutex pointer to env_rmutex which should be initiated
 * @retval 0
 */
static inline int env_rmutex_init(env_rmutex *rmutex)
{
	mutex_init(&rmutex->mutex);
	atomic_set(&rmutex->count, 0);
	rmutex->holder = NULL;
	return 0;
}

/**
 * @brief locks mutex inside env_rmutex struct and increment counter
 * @param rmutex pointer to env_rmutex which should be locked
 */
static inline void env_rmutex_lock(env_rmutex *rmutex)
{
	if (current == rmutex->holder) {
		atomic_inc(&rmutex->count);
		return;
	}

	mutex_lock(&rmutex->mutex);
	rmutex->holder = current;
	atomic_inc(&rmutex->count);
}

/**
 * @brief locks mutex inside env_rmutex struct and increment counter,
 * operation can be interrupted
 * @param rmutex pointer to env_rmutex which should be locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_INTR if interrupted
 */
static inline int env_rmutex_lock_interruptible(env_rmutex *rmutex)
{
	int result = 0;
	if (current == rmutex->holder) {
		atomic_inc(&rmutex->count);
		return 0;
	}

	result = mutex_lock_interruptible(&rmutex->mutex);
	if (result) {
		/* No lock */
		return -OCF_ERR_INTR;
	}

	rmutex->holder = current;
	atomic_inc(&rmutex->count);

	return 0;
}

/**
 * @brief tries to lock mutex inside env_rmutex struct and increment counter
 * @param rmutex pointer to env_rmutex which should be locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_NO_LOCK if failed
 */
static inline int env_rmutex_trylock(env_rmutex *rmutex)
{
	if (current == rmutex->holder) {
		atomic_inc(&rmutex->count);
		return 0;
	}

	if (mutex_trylock(&rmutex->mutex)) {
		/* No lock */
		return -OCF_ERR_NO_LOCK;
	}

	rmutex->holder = current;
	atomic_inc(&rmutex->count);

	return 0;
}

/**
 * @brief unlocks mutex inside env_rmutex struct and decrement counter
 * @param rmutex pointer to env_rmutex which should be unlocked
 * @bug assert if rmutex's holder is not equal to current system holder
 */
static inline void env_rmutex_unlock(env_rmutex *rmutex)
{
	BUG_ON(current != rmutex->holder);

	if (atomic_dec_return(&rmutex->count)) {
		return;
	}

	rmutex->holder = NULL;
	mutex_unlock(&rmutex->mutex);
}

/**
 * @brief checks if mutex inside env_rmutex struct is locked
 * @param rmutex pointer to env_rmutex which should be checked
 */
static inline int env_rmutex_is_locked(env_rmutex *rmutex)
{
	return mutex_is_locked(&rmutex->mutex);
}

static inline void env_rmutex_destroy(env_rmutex *rmutex)
{
}
/** @} */

/** @addtogroup RW_SEMAPHORE
 * @{
 */

/**
 * @struct env_rwsem ocf_env.h "modules/cas_cache/ocf_env.h"
 * @brief single read-write semaphore struct with waitqueue
 * @details contains:
 * <tt>struct rw_semaphore sem</tt> - read-write semaphore
 * <tt>wait_queue_head_t wq</tt> - waitqueue
 */
typedef struct
{
	struct rw_semaphore sem;
	wait_queue_head_t wq;
} env_rwsem;

/**
 * @brief initiates semaphore inside env_rwsem struct and add it to waitqueue
 * @param s pointer to env_rwsem which should be initiated
 * @retval 0 if succeed
 */
static inline int env_rwsem_init(env_rwsem *s)
{
	init_rwsem(&s->sem);
	init_waitqueue_head(&s->wq);
	return 0;
}

/**
 * @brief unlocks semaphore for read inside env_rwsem struct and wakes up
 * whole waitqueue
 * @param s pointer to env_rwsem which should be read-unlocked
 */
static inline void env_rwsem_up_read(env_rwsem *s)
{
	up_read(&s->sem);
	wake_up_all(&s->wq);
}

/**
 * @brief locks semaphore for read inside env_rwsem struct
 * @param s pointer to env_rwsem which should be read-locked
 */
static inline void env_rwsem_down_read(env_rwsem *s)
{
	down_read(&s->sem);
}

/**
 * @brief tries to lock semaphore for read inside env_rwsem struct,
 * operation can be interrupted
 * @param s pointer to env_rwsem which should be read-locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_INTR if failed
 */
static inline int env_rwsem_down_read_interruptible(env_rwsem *s)
{
	return wait_event_interruptible(s->wq,
			down_read_trylock(&s->sem)) ? -OCF_ERR_INTR : 0;
}

/**
 * @brief tries to lock semaphore for read inside env_rwsem struct
 * @param s pointer to env_rwsem which should be read-locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_NO_LOCK if failed
 */
static inline int env_rwsem_down_read_trylock(env_rwsem *s)
{
	return down_read_trylock(&s->sem) ? 0 : -OCF_ERR_NO_LOCK;
}

/**
 * @brief unlocks semaphore for write inside env_rwsem struct and wakes up
 * whole waitqueue
 * @param s pointer to env_rwsem which should be write-unlocked
 */
static inline void env_rwsem_up_write(env_rwsem *s)
{
	up_write(&s->sem);
	wake_up_all(&s->wq);
}

/**
 * @brief locks semaphore for write inside env_rwsem struct
 * @param s pointer to env_rwsem which should be write-locked
 */
static inline void env_rwsem_down_write(env_rwsem *s)
{
	down_write(&s->sem);
}

/**
 * @brief tries to lock semaphore for write inside env_rwsem struct,
 * operation can be interrupted
 * @param s pointer to env_rwsem which should be write-locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_INTR if failed
 */
static inline int env_rwsem_down_write_interruptible(env_rwsem *s)
{
	return wait_event_interruptible(s->wq,
			down_write_trylock(&s->sem)) ? -OCF_ERR_INTR : 0;
}

/**
 * @brief tries to lock semaphore for write inside env_rwsem struct
 * @param s pointer to env_rwsem which should be write-locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_NO_LOCK if failed
 */
static inline int env_rwsem_down_write_trylock(env_rwsem *s)
{
	return down_write_trylock(&s->sem) ? 0 : -OCF_ERR_NO_LOCK;
}

/**
 * @brief checks if semaphore inside env_rwsem struct is locked
 * @param s pointer to env_rwsem which should be checked
 */
static inline int env_rwsem_is_locked(env_rwsem *s)
{
	return rwsem_is_locked(&s->sem);
}

/**
 * @brief returns 0
 * @retval 0
 */
static inline int env_rwsem_destroy(env_rwsem *s)
{
	return 0;
}
/** @} */

/** @addtogroup COMPLETION
 * @{
 */

/**
 * @struct env_completion ocf_env.h "modules/cas_cache/ocf_env.h"
 * @brief wrapper for completion struct
 * @details contains:
 * <tt>unsigned int done</tt> - is completion done
 * <tt>wait_queue_head_t wait</tt> - waitqueue head
 */
typedef struct completion env_completion;


/**
 * @brief initiates completion inside env_completion struct
 * @param completion pointer to env_completion which should be initiated
 */
static inline void env_completion_init(env_completion *completion)
{
	init_completion(completion);
}

/**
 * @brief waits for completion inside env_completion struct to finish
 * @param completion pointer to env_completion to wait for
 */
static inline void env_completion_wait(env_completion *completion)
{
	wait_for_completion(completion);
}

/**
 * @brief finishes completion inside env_completion struct
 * @param completion pointer to env_completion which should be finished
 */
static inline void env_completion_complete(env_completion *completion)
{
	complete(completion);
}

static inline void env_completion_destroy(env_completion *completion)
{
}
/** @} */

/** @addtogroup ATOMIC_VARIABLES
 * @{
 */

/**
 * @brief wrappers for atomic variables types
 */
typedef atomic_t env_atomic;
typedef atomic64_t env_atomic64;

/**
 * @brief reads current env_atomic variable value
 * @param a pointer to constant env_atomic variable
 * @retval current atomic variable value
 */
static inline int env_atomic_read(const env_atomic *a)
{
	return atomic_read(a);
}

/**
 * @brief sets current env_atomic variable value
 * @param a pointer to env_atomic variable
 * @param i integer value to which \a a be set
 */
static inline void env_atomic_set(env_atomic *a, int i)
{
	atomic_set(a, i);
}

/**
 * @brief increases current env_atomic variable value
 * @param i integer value which would be added to \a a
 * @param a pointer to env_atomic variable
 */
static inline void env_atomic_add(int i, env_atomic *a)
{
	atomic_add(i, a);
}

/**
 * @brief decreases current env_atomic variable value
 * @param i integer value which would be subtracted from \a a
 * @param a pointer to env_atomic variable
 */
static inline void env_atomic_sub(int i, env_atomic *a)
{
	atomic_sub(i, a);
}

/**
 * @brief decreases current env_atomic variable value and checks its correctness
 * @param i integer value which would be subtracted from \a a
 * @param a pointer to env_atomic variable
 * @retval true if result is zero
 * @retval false in all other cases
 */
static inline bool env_atomic_sub_and_test(int i, env_atomic *a)
{
	return atomic_sub_and_test(i, a);
}

/**
 * @brief increments current env_atomic variable value
 * @param a pointer to env_atomic variable
 */
static inline void env_atomic_inc(env_atomic *a)
{
	atomic_inc(a);
}

/**
 * @brief decrements current env_atomic variable value
 * @param a pointer to env_atomic variable
 */
static inline void env_atomic_dec(env_atomic *a)
{
	atomic_dec(a);
}

/**
 * @brief decrements current env_atomic variable value and checks if its zero
 * @param a pointer to env_atomic variable
 * @retval true if result is zero
 * @retval false in all other cases
 */
static inline bool env_atomic_dec_and_test(env_atomic *a)
{
	return atomic_dec_and_test(a);
}

/**
 * @brief increments current env_atomic variable value and checks if its zero
 * @param a pointer to env_atomic variable
 * @retval true if result is zero
 * @retval false in all other cases
 */
static inline bool env_atomic_inc_and_test(env_atomic *a)
{
	return atomic_inc_and_test(a);
}

/**
 * @brief increases current env_atomic variable value and returns result
 * @param i integer value which would be added to \a a
 * @param a pointer to env_atomic variable
 * @retval result
 */
static inline int env_atomic_add_return(int i, env_atomic *a)
{
	return atomic_add_return(i, a);
}

/**
 * @brief decreases current env_atomic variable value and returns result
 * @param i integer value which would be subtracted from \a a
 * @param a pointer to env_atomic variable
 * @retval result
 */
static inline int env_atomic_sub_return(int i, env_atomic *a)
{
	return atomic_sub_return(i, a);
}

/**
 * @brief increments current env_atomic variable value and returns result
 * @param a pointer to env_atomic variable
 * @retval result
 */
static inline int env_atomic_inc_return(env_atomic *a)
{
	return atomic_inc_return(a);
}

/**
 * @brief decrements current env_atomic variable value and returns result
 * @param a pointer to env_atomic variable
 * @retval result
 */
static inline int env_atomic_dec_return(env_atomic *a)
{
	return atomic_dec_return(a);
}

/**
 * @brief checks if current env_atomic variable value equals given value
 * and exchange it to new value if yes
 * @param a pointer to env_atomic variable
 * @param old value with which \a a would be compared
 * @param new_value potentially new value
 * @retval current value of \a a
 */
static inline int env_atomic_cmpxchg(env_atomic *a, int old, int new_value)
{
	return atomic_cmpxchg(a, old, new_value);
}

/**
 * @brief checks if given value to doesn't equals another given value 
 * and add it to current env_atomic variable value
 * @param a pointer to env_atomic variable
 * @param i value which would be potentially added to \a a
 * @param u value with which \a i would be compared
 * @retval 0 if \a i equals \a u
 * @retval !0 in all other cases
 */
static inline int env_atomic_add_unless(env_atomic *a, int i, int u)
{
	return atomic_add_unless(a, i, u);
}

/**
 * @brief reads current env_atomic64 variable value
 * @param a pointer to constant env_atomic64 variable
 * @retval current atomic variable value
 */
static inline u64 env_atomic64_read(const env_atomic64 *a)
{
	return atomic64_read(a);
}

/**
 * @brief sets current env_atomic64 variable value
 * @param a pointer to env_atomic64 variable
 * @param i integer value to which \a a be set
 */
static inline void env_atomic64_set(env_atomic64 *a, u64 i)
{
	atomic64_set(a, i);
}

/**
 * @brief increases current env_atomic64 variable value
 * @param i integer value which would be added to \a a
 * @param a pointer to env_atomic64 variable
 */
static inline void env_atomic64_add(u64 i, env_atomic64 *a)
{
	atomic64_add(i, a);
}

/**
 * @brief decreases current env_atomic64 variable value
 * @param i integer value which would be subtracted from \a a
 * @param a pointer to env_atomic64 variable
 */
static inline void env_atomic64_sub(u64 i, env_atomic64 *a)
{
	atomic64_sub(i, a);
}

/**
 * @brief increments current env_atomic64 variable value
 * @param a pointer to env_atomic64 variable
 */
static inline void env_atomic64_inc(env_atomic64 *a)
{
	atomic64_inc(a);
}

/**
 * @brief decrements current env_atomic64 variable value
 * @param a pointer to env_atomic64 variable
 */
static inline void env_atomic64_dec(env_atomic64 *a)
{
	atomic64_dec(a);
}

/**
 * @brief increments current env_atomic64 variable value and returns result
 * @param a pointer to env_atomic variable
 * @retval result
 */
static inline u64 env_atomic64_inc_return(env_atomic64 *a)
{
	return atomic64_inc_return(a);
}

/**
 * @brief checks if current env_atomic64 variable value equals given value
 * and exchange it to new value if yes
 * @param a pointer to env_atomic64 variable
 * @param old value with which \a a would be compared
 * @param new_value potentially new value
 * @retval current value of \a a
 */
static inline u64 env_atomic64_cmpxchg(atomic64_t *a, u64 old, u64 new)
{
	return atomic64_cmpxchg(a, old, new);
}
/** @} */

/** @addtogroup SPIN_LOCKS
 * @{
 */

/**
 * @brief wrapper for spinlock_t
 */
typedef spinlock_t env_spinlock;

/**
 * @brief initiates env_spinlock
 * @param l pointer to env_spinlock which should be initiated
 * @retval 0 if succeed
 */
static inline int env_spinlock_init(env_spinlock *l)
{
	spin_lock_init(l);
	return 0;
}

/**
 * @brief locks env_spinlock
 * @param l pointer to env_spinlock which should be locked
 */
static inline void env_spinlock_lock(env_spinlock *l)
{
	spin_lock(l);
}

/**
 * @brief tries to lock env_spinlock
 * @param l pointer to env_spinlock which should be locked
 * @retval 0 if succeed
 * @retval -OCF_ERR_NO_LOCK if failed
 */
static inline int env_spinlock_trylock(env_spinlock *l)
{
	return spin_trylock(l) ? 0 : -OCF_ERR_NO_LOCK;
}

/**
 * @brief unlocks env_spinlock
 * @param l pointer to env_spinlock which should be unlocked
 */
static inline void env_spinlock_unlock(env_spinlock *l)
{
	spin_unlock(l);
}

/**
 * @brief waits until env_spinlock is retrieved and disables interrupts
 * @param l pointer to env_spinlock which should be locked
 */
static inline void env_spinlock_lock_irq(env_spinlock *l)
{
	spin_lock_irq(l);
}

/**
 * @brief releases env_spinlock and restores interrupts
 * @param l pointer to env_spinlock which should be locked
 */
static inline void env_spinlock_unlock_irq(env_spinlock *l)
{
	spin_unlock_irq(l);
}

static inline void env_spinlock_destroy(env_spinlock *l)
{
}

/**
 * @def env_spinlock_lock_irqsave(l, flags)
 * @brief waits until spinlock is retrieved and disables interrupts 
 * with saving previous interrupt state
 */
#define env_spinlock_lock_irqsave(l, flags) \
		spin_lock_irqsave((l), (flags))

/**
 * @def env_spinlock_unlock_irqrestore(l, flags)
 * @brief releases spinlock and restores interrupts with loading
 * previous interrupt state
 */
#define env_spinlock_unlock_irqrestore(l, flags) \
		spin_unlock_irqrestore((l), (flags))
/** @} */

/** @addtogroup RW_LOCKS
 * @{
 */

/**
 * @brief wrapper for rwlock_t
 */
typedef rwlock_t env_rwlock;

/**
 * @brief initiates env_rwlock
 * @param l pointer to env_rwlock which should be initiated
 */
static inline void env_rwlock_init(env_rwlock *l)
{
	rwlock_init(l);
}

/**
 * @brief locks env_rwlock for read
 * @param s pointer to env_rwlock which should be read-locked
 */
static inline void env_rwlock_read_lock(env_rwlock *l)
{
	read_lock(l);
}

/**
 * @brief unlocks env_rwlock for read
 * @param s pointer to env_rwlock which should be read-unlocked
 */
static inline void env_rwlock_read_unlock(env_rwlock *l)
{
	read_unlock(l);
}

/**
 * @brief locks env_rwlock for write
 * @param s pointer to env_rwlock which should be write-locked
 */
static inline void env_rwlock_write_lock(env_rwlock *l)
{
	write_lock(l);
}

/**
 * @brief unlocks env_rwlock for write
 * @param s pointer to env_rwlock which should be write-unlocked
 */
static inline void env_rwlock_write_unlock(env_rwlock *l)
{
	write_unlock(l);
}

static inline void env_rwlock_destroy(env_rwlock *l)
{
}
/** @} */

/** @addtogroup WAITQUEUE
 * @{
 */

/**
 * @brief wrapper for wait_queue_head_t
 */
typedef wait_queue_head_t env_waitqueue;

/**
 * @brief initiates env_waitqueue
 * @param w pointer to env_waitqueue which should be initiated
 */
static inline void env_waitqueue_init(env_waitqueue *w)
{
	init_waitqueue_head(w);
}

/**
 * @brief wakes up env_waitqueue
 * @param w pointer to env_waitqueue which should be woken up
 */
static inline void env_waitqueue_wake_up(env_waitqueue *w)
{
	wake_up(w);
}

/**
 * @brief puts env_waitqueue in wait state, operation can be interrupted
 * @param w pointer to env_waitqueue which should wait
 */
#define env_waitqueue_wait(w, condition) \
		wait_event_interruptible((w), (condition))
/** @} */

/** @addtogroup SCHEDULING
 * @{
 */

/**
 * @brief reschedule task
 */
static inline void env_cond_resched(void)
{
	cond_resched();
}

/**
 * @brief checks if task is in interrupt
 * @retval true if in interrupt
 * @retval false otherwise
 */
static inline int env_in_interrupt(void)
{
	return in_interrupt();
}
/** @} */

/** @addtogroup TIME
 * @{
 */

/**
 * @brief checks current tick
 * @retval current ticks
 */
static inline uint64_t env_get_tick_count(void)
{
	return jiffies;
}

/**
 * @brief converts ticks to miliseconds
 * @param j number of ticks to convert
 * @retval miliseconds
 */
static inline uint64_t env_ticks_to_msecs(uint64_t j)
{
	return jiffies_to_msecs(j);
}

/**
 * @brief converts ticks to nanoseconds
 * @param j number of ticks to convert
 * @retval nanoseconds
 */
static inline uint64_t env_ticks_to_nsecs(uint64_t j)
{
	return jiffies_to_usecs(j) * NSEC_PER_USEC;
}

/**
 * @brief counts difference between end value and start value
 * @param a start tick value
 * @param b end tick value
 * @retval difference in ticks
 */
static inline bool env_time_after(uint64_t a, uint64_t b)
{
	return time_after64(a,b);
}

/**
 * @brief converts ticks to seconds
 * @param j number of ticks to convert
 * @retval seconds
 */
static inline uint64_t env_ticks_to_secs(uint64_t j)
{
	return j >> SHIFT_HZ;
}

/**
 * @brief converts seconds to ticks
 * @param j number of seconds to convert
 * @retval ticks
 */
static inline uint64_t env_secs_to_ticks(uint64_t j)
{
	return j << SHIFT_HZ;
}

/**
 * @brief sleeps for given amount of miliseconds
 * @param n number of miliseconds to sleep for
 */
static inline void env_msleep(uint64_t n)
{
	msleep(n);
}
/** @} */

/** @addtogroup BIT_OPERATIONS
 * Functions using built-ins for atomic memory access
 * @{
 */


/**
 * @brief sets bit value to 1
 * @param nr 32-bit number
 * @param addr pointer to volatile address
 */
static inline void env_bit_set(int nr, volatile void *addr)
{
	set_bit(nr, addr);
}

/**
 * @brief clears bit value - sets it to zero
 * @param nr 32-bit number
 * @param addr pointer to volatile address
 */
static inline void env_bit_clear(int nr, volatile void *addr)
{
	clear_bit(nr, addr);
}

/**
 * @brief checks bit value
 * @param nr 32-bit number
 * @param addr pointer to volatile address
 */
static inline int env_bit_test(int nr, const void *addr)
{
	return test_bit(nr, addr);
}
/** @} */

/** @addtogroup STRING_OPERATIONS 
 * definitions for custom string operations
 * @{
 */

/**
 * @def env_memset(dest, dmax, val)
 * @brief fills chosen memory block with chosen value
 */
#define env_memset(dest, dmax, val) ({ \
		memset(dest, val, dmax); \
		0; \
	})

/**
 * @def env_memcpy(dest, dmax, src, slen)
 * @brief copies chosen part of memory to another with check
 * if source part doesn't exceeds destination's free space
 * and if so, copy just part of source's memory block
 */
#define env_memcpy(dest, dmax, src, slen) ({ \
		memcpy(dest, src, min_t(int, dmax, slen)); \
		0; \
	})

/**
 * @def env_memcmp(s1, s1max, s2, s2max, diff)
 * @brief compares chosen memory block with other with check
 * if one block isn't bigger than another and if so, compares
 * only equal to smaller block's size part of the bigger one
 */
#define env_memcmp(s1, s1max, s2, s2max, diff) ({ \
		*diff = memcmp(s1, s2, min_t(int, s1max, s2max)); \
		0; \
	})
/**
 * @def env_strdup
 * @brief returns pointer to allocated space with copied terminated 
 * string of at most N bytes
 */
#define env_strdup kstrdup

/**
 * @def env_strnlen(s, smax)
 * @brief checks if string terminates in \a smax bytes and return its lenght,
 * otherwise returns \a smax
 */
#define env_strnlen(s, smax) strnlen(s, smax)

/**
 * @def env_strncmp(s1, slen1, s2, slen2)
 * @brief compares chosen string with other with check if one string
 * isn't shorter than minimum and isn't longer than another and if so,
 * compares only equal to shorter string's size part of the longer one
 */
#define env_strncmp(s1, slen1, s2, slen2) strncmp(s1, s2, \
					min_t(size_t, slen1, slen2))

/**
 * @def env_strncpy(dest, dmax, src, slen)
 * @brief copies chosen string check if it isn't shorter than minimum 
 * and isn't longer than destination place and if so, copies only equal 
 * to shorter lenght's size part of the longer one
 */
#define env_strncpy(dest, dmax, src, slen) ({ \
		strlcpy(dest, src, min_t(int, dmax, slen)); \
		0; \
	})
/** @} */

/** @addtogroup SORTING
 * @{
 */

/**
 * @brief sorts structure with quicksort algorithm
 * @param base structure to be sorted
 * @param num amount of elements of \a base to be sorted
 * @param size size of single \a base's element in bytes
 * @param cmp_fn pointer to comparing function receiving two constant void
 * pointers and returning int
 * @param swap_fn pointer to swaping function receiving two void pointers and int
 */
void env_sort(void *base, size_t num, size_t size,
	int (*cmp_fn)(const void *, const void *),
	void (*swap_fn)(void *, void *, int size));
/** @} */

/** @addtogroup CRC
 * @{
 */

/**
 * @brief Updates a running CRC-32
 * wrapper for crc32 function from \a <zlib.h> library
 * @param crc cyclic redundancy code
 * @param data pointer to data that would be checked
 * @param len amount of \a data's elements that would be checked
 * @retval updated CRC-32
 */
static inline uint32_t env_crc32(uint32_t crc, uint8_t const *data, size_t len)
{
	return crc32(crc, data, len);
}
/** @} */

/** @addtogroup LOGGING
 * @{
 */

/**
 * @def ENV_PRIu64
 * @brief expands to 'long long unsigned' abbreviation, used in formatting
 */
#define ENV_PRIu64 "llu"
#define ENV_PRId64 "lld"

/**
 * @def ENV_WARN(cond, fmt...)
 * @brief wrapper for kernel macro WARN
 */
#define ENV_WARN(cond, fmt...)		WARN(cond, fmt)

/**
 * @def ENV_WARN_ON(cond)
 * @brief wrapper for kernel macro WARN_ON
 */
#define ENV_WARN_ON(cond)		WARN_ON(cond)

/**
 * @def ENV_BUG()
 * @brief wrapper for kernel macro BUG
 */
#define ENV_BUG()			BUG()

/**
 * @def ENV_BUG_ON(cond)
 * @brief wrapper for kernel macro BUG_ON
 */
#define ENV_BUG_ON(cond)		BUG_ON(cond)

/**
 * @def ENV_BUILD_BUG_ON(cond)
 * @brief wrapper for kernel macro BUILD_BUG_ON
 */
#define ENV_BUILD_BUG_ON(cond)		BUILD_BUG_ON(cond)
/** @} */

/** @addtogroup EXECUTION_CONTEXTS
 * @{
 */

/** 
 * @brief gets execution context
 * @retval 0 if succeed
 * @retval -1 if failed
 */
static inline unsigned env_get_execution_context(void)
{
	return get_cpu();
}

/** 
 * @brief leaves execution context
 * @param ctx context which should be leaved
 */
static inline void env_put_execution_context(unsigned ctx)
{
	put_cpu();
}

/** 
 * @brief checks number of available contexts
 * @retval number of currently available contexts
 */
static inline unsigned env_get_execution_context_count(void)
{
	return num_online_cpus();
}
/** @} */

#endif /* __OCF_ENV_H__ */
