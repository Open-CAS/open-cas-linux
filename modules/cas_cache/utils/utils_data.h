/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef UTILS_DATA_H_
#define UTILS_DATA_H_

/**
 * @brief Copy data from a data vector to another one
 *
 * This function copies number of bytes from source IO vector to destination
 * IO vector. It starts coping to specified offset in destination IO vector. If
 * there is not enough space it will return number of bytes that was
 * successfully copied.
 *
 * @param dst destination IO vector
 * @param dst_num size of destination IO vector
 * @param src source IO vector
 * @param src_num size of source IO vector
 * @param to dst offset where write to will start
 * @param from src offset where write from will start
 * @param bytes number of bytes to be copied
 *
 * @return number of bytes written from src to dst
 */
uint64_t cas_data_cpy(struct bio_vec *dst, uint64_t dst_num,
		struct bio_vec *src, uint64_t src_num,
		uint64_t to, uint64_t from, uint64_t bytes);

#endif /* UTILS_DATA_H_ */
