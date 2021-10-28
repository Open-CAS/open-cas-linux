/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef PSORT_H
#define PSORT_H
typedef int (*compar_t)(const void *, const void *);

/**
 * function does exactly the same thing as qsort, except, that it sorts
 * using many CPU cores, not just one.
 *
 * number of CPU cores is configured as half of the number of online
 * CPUs in the system.
 */
void psort(void *base, size_t nmemb, size_t size,
	   compar_t compar);


#endif

