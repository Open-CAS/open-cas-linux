/*
 * Copyright(c) 2012-2021 Intel Corporation
 * SPDX-License-Identifier: BSD-3-Clause-Clear
 */

#ifndef UTILS_MPOOL_H_
#define UTILS_MPOOL_H_

#define ALLOCATOR_NAME_MAX 128

enum {
	cas_mpool_1,
	cas_mpool_2,
	cas_mpool_4,
	cas_mpool_8,
	cas_mpool_16,
	cas_mpool_32,
	cas_mpool_64,
	cas_mpool_128,

	cas_mpool_max
};

struct cas_mpool {
	uint32_t item_size;
		/*!< Size of specific item of memory pool */

	uint32_t hdr_size;
		/*!< Header size before items */

	env_allocator *allocator[cas_mpool_max];
		/*!< OS handle to memory pool */

	int flags;
		/*!< Allocation flags */
};

/**
 * @brief Create CAS memory pool
 *
 * @param hdr_size Header size before array of items
 * @param size Size of particular item
 * @param flags Allocation flags
 * @param mpool_max Maximal allocator size (power of two)
 * @param name_prefix Format name prefix
 *
 * @return CAS memory pool
 */
struct cas_mpool *cas_mpool_create(uint32_t hdr_size, uint32_t size, int flags,
		int mpool_max, const char *name_perfix);

/**
 * @brief Destroy existing memory pool
 *
 * @param mpool memory pool
 */
void cas_mpool_destroy(struct cas_mpool *mpool);

/**
 * @brief Allocate new items of memory pool
 *
 * @note Allocation based on ATOMIC memory pool and this function can be called
 * when IRQ disable
 *
 * @param mpool CAS memory pool reference
 * @param count Count of elements to be allocated
 *
 * @return Pointer to the new items
 */
void *cas_mpool_new(struct cas_mpool *mpool, uint32_t count);

/**
 * @brief Allocate new items of memory pool with specified allocation flag
 *
 * @param mpool CAS memory pool reference
 * @param count Count of elements to be allocated
 * @param flags Kernel allocation falgs
 *
 * @return Pointer to the new items
 */
void *cas_mpool_new_f(struct cas_mpool *mpool, uint32_t count, int flags);

/**
 * @brief Free existing items of memory pool
 *
 * @param mpool CAS memory pool reference
 * @param items Items to be freed
 * @param count - Count of elements to be free
 */
void cas_mpool_del(struct cas_mpool *mpool, void *items, uint32_t count);

#endif /* UTILS_MPOOL_H_ */
