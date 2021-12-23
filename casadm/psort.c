/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/timeb.h>
#include <pthread.h>
#include <string.h>
#include <stdbool.h>
#include "safeclib/safe_mem_lib.h"
#include "psort.h"

/**
 * internal state of parallel sort algorithm (entire task for main thread,
 * subtask for children).
 */
struct psort_state
{
	void *defbase; /*!< base of master buffer sort
			 * - needed to compute offsets*/
	int spawn_threads;
	void *base; /*!< base of subtask */
	size_t nmemb; /*!< number of members in subtask */
	size_t size; /*!< of each member */
	compar_t compar;
	int result; /*!< partial result */
	void *tmpbuf; /*!< temporary buffer for purpose of merge algorithm */
};

void memcpy_replacement(void *dst, void *src, size_t size)
{
	/**
	 * Avoid this if possible. memcpy_s leads to crappy performance
	 * defeating purpose of entire optimized sort.
	 */
	memcpy_s(dst, size, src, size);
}

/**
 * merge algorithm has O(N) spatial complexity and O(N) time complexity
 */
void merge_ranges(void *base, size_t nmemb1, size_t nmemb2, size_t size,
		  compar_t compar, void *tmpbuf)
{
	void *target_buf = tmpbuf;
	int i1, i2;

	for (i1 = i2 = 0; i1 < nmemb1 || i2 < nmemb2;) {
		bool lil; /* lil means "left is less" */
		if (i1 == nmemb1) {
			lil = false;
		} else if (i2 ==nmemb2) {
			lil = true;
		} else if (compar(base + i1 * size,
				  base + (nmemb1 +i2) * size) < 0) {
			lil = true;
		} else {
			lil = false;

		}
		if (lil) {
			memcpy_replacement(target_buf + (i1 + i2) * size,
			       base + i1 * size,
			       size);
			i1++;
		} else {
			memcpy_replacement(target_buf + (i1 + i2) * size,
			       base + (nmemb1 + i2) * size,
			       size);
			i2++;
		}
	}
	memcpy_replacement(base, target_buf, (nmemb1 + nmemb2) * size);
}

/**
 * Execute quicksort on part or entirety of subrange. If subranges taken into
 * account, than merge partial sort results.
 *
 * Complexity          |      time         |    spatial
 * --------------------+-------------------+-----------
 * Quick Sort          |  O(n*lg(n)/ncpu)  |    O(1)
 * Merging             |       O(n)        |    O(N)
 * --------------------+-------------------+-----------
 * Entire algorithm    | O(n+n*lg(n)/ncpu) |    O(N)
 *
 * Effectively for suficiently large number of CPUs, sorting time
 * becomes linear to dataset:
 * \lim{ncpu \rightarrow \infty} O(n+\frac{n*lg(n)}{ncpu}) = O(n + 0^+) = O(n)
 * Less can't be achieved, as last merge can't be parallelized.
 */
void *psort_thread_fun(void *arg_v)
{
	pthread_t thread;
	struct psort_state* arg = arg_v;
	struct psort_state base_state;
		struct psort_state child_state;
	memcpy_replacement(&base_state, arg, sizeof(base_state));
	if (arg->spawn_threads > 1) {
		/* local state (assume, input state is unmodifiable) */
		memcpy_replacement(&child_state, arg, sizeof(base_state));

		base_state.spawn_threads /= 2;
		child_state.spawn_threads = arg->spawn_threads
			- base_state.spawn_threads;

		base_state.nmemb /= 2;
		child_state.nmemb = arg->nmemb - base_state.nmemb;

		child_state.base += base_state.size *
			base_state.nmemb;
		/* spawn child */
		if (pthread_create(&thread, 0, psort_thread_fun, &child_state)) {
			/* failed to create thread */
			arg->result = -errno;
			return arg_v;
		}
	}

	if (1 == base_state.spawn_threads) {
		qsort(base_state.base, base_state.nmemb,
		      base_state.size, base_state.compar);
	} else {
		psort_thread_fun(&base_state);
		if (base_state.result) {
			arg->result = base_state.result;
		}
	}

	if (arg->spawn_threads > 1) {
		if (pthread_join(thread, 0)) {
			arg->result = -errno;
			return arg_v;
		}
		if (child_state.result) {
			arg->result = child_state.result;
			return arg_v;
		}
		if (!arg->result) {
			merge_ranges(arg->base, base_state.nmemb,
				     child_state.nmemb, arg->size,
				     arg->compar,
				     arg->tmpbuf + (base_state.base
						    - base_state.defbase));
		}
	}
	return arg_v;
}

/**
 * actual parallel sorting entry point
 */
int psort_main(void *base, size_t nmemb, size_t size,
	       compar_t compar, int ncpu)
{
	struct psort_state base_state;
	/* use half the number of logical CPUs for purpose of sorting */
	base_state.spawn_threads = ncpu;
	/* current num of CPUs */
	base_state.defbase = base;
	base_state.base = base;
	base_state.nmemb = nmemb;
	base_state.size = size;
	base_state.compar = compar;
	base_state.tmpbuf = malloc(size * nmemb);
	base_state.result = 0;
	if (!base_state.tmpbuf) {
		return -1;
	}
	psort_thread_fun(&base_state);
	free(base_state.tmpbuf);
	return base_state.result;
}

void psort(void *base, size_t nmemb, size_t size,
	  compar_t compar)
{
	/* entry point to psort */
	int ncpu = sysconf(_SC_NPROCESSORS_ONLN)/2;
	int maxncpu = nmemb / 1024;
	if (maxncpu < ncpu) {
		ncpu = maxncpu;
	}
	/* don't invoke actual psort when less than 2 threads are needed */
	if (ncpu < 2) {
		qsort(base, nmemb, size, compar);
	} else {
		if (psort_main(base, nmemb, size, compar, ncpu)) {
			/* if parallel sorting failed (i.e. due to failed thread
			 * creation, fall back to single threaded operation */
			qsort(base, nmemb, size, compar);
		}
	}
}
