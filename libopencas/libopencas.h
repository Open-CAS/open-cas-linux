/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Userspace client library for the Open CAS Generic Netlink interface.
 *
 * Provides parsed C structures and a single-call API to dump all CAS
 * state. Intended for use by casadm, Prometheus exporter, and other
 * userspace consumers.
 */

#ifndef LIBOPENCAS_H
#define LIBOPENCAS_H

#include <stdint.h>
#include <stdbool.h>

#define CAS_NL_PATH_MAX			4096
#define CAS_NL_IOCLASS_NAME_MAX		1024

struct cas_nl_stats {
	/* Usage (4 KiB units) */
	uint64_t usage_occupancy;
	uint64_t usage_free;
	uint64_t usage_clean;
	uint64_t usage_dirty;

	/* Requests */
	uint64_t req_rd_hits;
	uint64_t req_rd_deferred;
	uint64_t req_rd_partial_misses;
	uint64_t req_rd_full_misses;
	uint64_t req_rd_total;
	uint64_t req_wr_hits;
	uint64_t req_wr_deferred;
	uint64_t req_wr_partial_misses;
	uint64_t req_wr_full_misses;
	uint64_t req_wr_total;
	uint64_t req_rd_pt;
	uint64_t req_wr_pt;
	uint64_t req_serviced;
	uint64_t req_prefetch_readahead;
	uint64_t req_cleaner;
	uint64_t req_total;

	/* Blocks (4 KiB units) */
	uint64_t blocks_core_rd;
	uint64_t blocks_core_wr;
	uint64_t blocks_core_total;
	uint64_t blocks_cache_rd;
	uint64_t blocks_cache_wr;
	uint64_t blocks_cache_total;
	uint64_t blocks_volume_rd;
	uint64_t blocks_volume_wr;
	uint64_t blocks_volume_total;
	uint64_t blocks_pt_rd;
	uint64_t blocks_pt_wr;
	uint64_t blocks_pt_total;
	uint64_t blocks_prefetch_core_rd_readahead;
	uint64_t blocks_prefetch_cache_wr_readahead;
	uint64_t blocks_cleaner_cache_rd;
	uint64_t blocks_cleaner_core_wr;

	/* Errors */
	uint64_t errors_core_rd;
	uint64_t errors_core_wr;
	uint64_t errors_core_total;
	uint64_t errors_cache_rd;
	uint64_t errors_cache_wr;
	uint64_t errors_cache_total;
	uint64_t errors_total;
};

struct cas_nl_cleaning_params {
	uint32_t policy;
	uint32_t alru_wake_up;
	uint32_t alru_stale_time;
	uint32_t alru_flush_max_buffers;
	uint32_t alru_activity_threshold;
	uint32_t alru_dirty_ratio_threshold;
	uint32_t alru_dirty_ratio_inertia;
	uint32_t acp_wake_up;
	uint32_t acp_flush_max_buffers;
};

struct cas_nl_promotion_params {
	uint32_t policy;
	uint32_t nhit_insertion_threshold;
	uint32_t nhit_trigger_threshold;
};

struct cas_nl_cache {
	uint16_t id;
	char path[CAS_NL_PATH_MAX];

	uint8_t state;
	uint8_t mode;
	uint32_t line_size;
	bool attached;
	bool standby_detached;

	uint32_t size;
	uint32_t occupancy;
	uint32_t dirty;
	uint64_t dirty_for;
	uint32_t dirty_initial;
	uint32_t flushed;
	uint32_t core_count;

	uint64_t metadata_footprint;
	uint32_t metadata_end_offset;

	uint32_t fallback_pt_errors;
	uint8_t fallback_pt_status;

	uint64_t inactive_occupancy;
	uint64_t inactive_clean;
	uint64_t inactive_dirty;

	struct cas_nl_cleaning_params cleaning;
	struct cas_nl_promotion_params promotion;
	struct cas_nl_stats stats;
};

struct cas_nl_core {
	uint16_t cache_id;
	uint16_t id;
	char path[CAS_NL_PATH_MAX];

	uint8_t state;
	bool exp_obj_exists;

	uint64_t size;
	uint64_t size_bytes;

	uint32_t dirty;
	uint64_t dirty_for;
	uint32_t flushed;

	uint32_t seq_cutoff_threshold;
	uint8_t seq_cutoff_policy;
	uint32_t seq_cutoff_promo_count;

	struct cas_nl_stats stats;
};

struct cas_nl_ioclass {
	uint16_t cache_id;
	uint32_t id;
	char name[CAS_NL_IOCLASS_NAME_MAX];

	uint8_t cache_mode;
	int16_t priority;
	uint32_t curr_size;
	uint32_t min_size;
	uint32_t max_size;
	uint8_t cleaning_policy;

	struct cas_nl_stats stats;
};

struct cas_nl_dump_result {
	struct cas_nl_cache *caches;
	int num_caches;
	struct cas_nl_core *cores;
	int num_cores;
	struct cas_nl_ioclass *ioclasses;
	int num_ioclasses;
};

/**
 * cas_nl_dump() - dump all CAS state via Generic Netlink
 * @result: output structure filled with parsed records
 *
 * The caller must free the result with cas_nl_dump_free() when done.
 *
 * Return: 0 on success, negative errno on failure.
 */
int cas_nl_dump(struct cas_nl_dump_result *result);

/**
 * cas_nl_dump_free() - free memory allocated by cas_nl_dump()
 * @result: structure to free
 */
void cas_nl_dump_free(struct cas_nl_dump_result *result);

#endif /* LIBOPENCAS_H */
