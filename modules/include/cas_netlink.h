/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef CAS_NETLINK_H
#define CAS_NETLINK_H

#define CAS_NL_FAMILY_NAME	"opencas"
#define CAS_NL_FAMILY_VERSION	1

/**
 * Generic Netlink commands
 */
enum cas_nl_cmd {
	CAS_NL_CMD_UNSPEC,
	CAS_NL_CMD_DUMP,
	__CAS_NL_CMD_MAX,
};
#define CAS_NL_CMD_MAX (__CAS_NL_CMD_MAX - 1)

/**
 * Top-level attributes. Each dump message contains exactly one of
 * the nested record attributes below.
 */
enum cas_nl_attr {
	CAS_NL_A_UNSPEC,
	CAS_NL_A_CACHE,		/* NLA_NESTED - cache record */
	CAS_NL_A_CORE,		/* NLA_NESTED - core record */
	CAS_NL_A_IO_CLASS,	/* NLA_NESTED - IO class record */
	__CAS_NL_A_MAX,
};
#define CAS_NL_A_MAX (__CAS_NL_A_MAX - 1)

/**
 * Cache record attributes (inside CAS_NL_A_CACHE)
 */
enum cas_nl_cache_attr {
	CAS_NL_CACHE_A_UNSPEC,
	/* Identification */
	CAS_NL_CACHE_A_ID,			/* u16 */
	CAS_NL_CACHE_A_PATH,			/* NUL-string */
	/* Configuration */
	CAS_NL_CACHE_A_STATE,			/* u8 */
	CAS_NL_CACHE_A_MODE,			/* u8 */
	CAS_NL_CACHE_A_LINE_SIZE,		/* u32 */
	CAS_NL_CACHE_A_ATTACHED,		/* flag */
	CAS_NL_CACHE_A_STANDBY_DETACHED,	/* flag */
	/* Size and occupancy */
	CAS_NL_CACHE_A_SIZE,			/* u32 */
	CAS_NL_CACHE_A_OCCUPANCY,		/* u32 */
	CAS_NL_CACHE_A_DIRTY,			/* u32 */
	CAS_NL_CACHE_A_DIRTY_FOR,		/* u64 */
	CAS_NL_CACHE_A_DIRTY_INITIAL,		/* u32 */
	CAS_NL_CACHE_A_FLUSHED,			/* u32 */
	CAS_NL_CACHE_A_CORE_COUNT,		/* u32 */
	/* Metadata */
	CAS_NL_CACHE_A_METADATA_FOOTPRINT,	/* u64 */
	CAS_NL_CACHE_A_METADATA_END_OFFSET,	/* u32 */
	/* Fallback pass-through */
	CAS_NL_CACHE_A_FALLBACK_PT_ERRORS,	/* u32 */
	CAS_NL_CACHE_A_FALLBACK_PT_STATUS,	/* u8 */
	/* Inactive core stats */
	CAS_NL_CACHE_A_INACTIVE_OCCUPANCY,	/* u64 */
	CAS_NL_CACHE_A_INACTIVE_CLEAN,		/* u64 */
	CAS_NL_CACHE_A_INACTIVE_DIRTY,		/* u64 */
	/* Nested sub-records */
	CAS_NL_CACHE_A_CLEANING_PARAMS,		/* NLA_NESTED */
	CAS_NL_CACHE_A_PROMOTION_PARAMS,	/* NLA_NESTED */
	CAS_NL_CACHE_A_STATS,			/* NLA_NESTED */
	__CAS_NL_CACHE_A_MAX,
};
#define CAS_NL_CACHE_A_MAX (__CAS_NL_CACHE_A_MAX - 1)

/**
 * Cleaning parameters attributes (inside CAS_NL_CACHE_A_CLEANING_PARAMS)
 */
enum cas_nl_cleaning_attr {
	CAS_NL_CLEANING_A_UNSPEC,
	CAS_NL_CLEANING_A_POLICY,			/* u32 */
	CAS_NL_CLEANING_A_ALRU_WAKE_UP,			/* u32 */
	CAS_NL_CLEANING_A_ALRU_STALE_TIME,		/* u32 */
	CAS_NL_CLEANING_A_ALRU_FLUSH_MAX_BUFFERS,	/* u32 */
	CAS_NL_CLEANING_A_ALRU_ACTIVITY_THRESHOLD,	/* u32 */
	CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_THRESHOLD,	/* u32 */
	CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_INERTIA,	/* u32 */
	CAS_NL_CLEANING_A_ACP_WAKE_UP,			/* u32 */
	CAS_NL_CLEANING_A_ACP_FLUSH_MAX_BUFFERS,	/* u32 */
	__CAS_NL_CLEANING_A_MAX,
};
#define CAS_NL_CLEANING_A_MAX (__CAS_NL_CLEANING_A_MAX - 1)

/**
 * Promotion parameters attributes (inside CAS_NL_CACHE_A_PROMOTION_PARAMS)
 */
enum cas_nl_promotion_attr {
	CAS_NL_PROMOTION_A_UNSPEC,
	CAS_NL_PROMOTION_A_POLICY,			/* u32 */
	CAS_NL_PROMOTION_A_NHIT_INSERTION_THRESHOLD,	/* u32 */
	CAS_NL_PROMOTION_A_NHIT_TRIGGER_THRESHOLD,	/* u32 */
	__CAS_NL_PROMOTION_A_MAX,
};
#define CAS_NL_PROMOTION_A_MAX (__CAS_NL_PROMOTION_A_MAX - 1)

/**
 * Core record attributes (inside CAS_NL_A_CORE)
 */
enum cas_nl_core_attr {
	CAS_NL_CORE_A_UNSPEC,
	/* Identification */
	CAS_NL_CORE_A_CACHE_ID,			/* u16 */
	CAS_NL_CORE_A_ID,			/* u16 */
	CAS_NL_CORE_A_PATH,			/* NUL-string */
	/* State */
	CAS_NL_CORE_A_STATE,			/* u8 */
	CAS_NL_CORE_A_EXP_OBJ_EXISTS,		/* flag */
	/* Size */
	CAS_NL_CORE_A_SIZE,			/* u64 */
	CAS_NL_CORE_A_SIZE_BYTES,		/* u64 */
	/* Dirty data */
	CAS_NL_CORE_A_DIRTY,			/* u32 */
	CAS_NL_CORE_A_DIRTY_FOR,		/* u64 */
	CAS_NL_CORE_A_FLUSHED,			/* u32 */
	/* Sequential cutoff */
	CAS_NL_CORE_A_SEQ_CUTOFF_THRESHOLD,	/* u32 */
	CAS_NL_CORE_A_SEQ_CUTOFF_POLICY,	/* u8 */
	CAS_NL_CORE_A_SEQ_CUTOFF_PROMO_COUNT,	/* u32 */
	/* Stats */
	CAS_NL_CORE_A_STATS,			/* NLA_NESTED */
	__CAS_NL_CORE_A_MAX,
};
#define CAS_NL_CORE_A_MAX (__CAS_NL_CORE_A_MAX - 1)

/**
 * IO class record attributes (inside CAS_NL_A_IO_CLASS)
 */
enum cas_nl_ioclass_attr {
	CAS_NL_IOCLASS_A_UNSPEC,
	/* Identification */
	CAS_NL_IOCLASS_A_CACHE_ID,		/* u16 */
	CAS_NL_IOCLASS_A_ID,			/* u32 */
	CAS_NL_IOCLASS_A_NAME,			/* NUL-string */
	/* Configuration */
	CAS_NL_IOCLASS_A_CACHE_MODE,		/* u8 */
	CAS_NL_IOCLASS_A_PRIORITY,		/* u16 (int16 cast to u16) */
	CAS_NL_IOCLASS_A_CURR_SIZE,		/* u32 */
	CAS_NL_IOCLASS_A_MIN_SIZE,		/* u32 */
	CAS_NL_IOCLASS_A_MAX_SIZE,		/* u32 */
	CAS_NL_IOCLASS_A_CLEANING_POLICY,	/* u8 */
	/* Stats */
	CAS_NL_IOCLASS_A_STATS,			/* NLA_NESTED */
	__CAS_NL_IOCLASS_A_MAX,
};
#define CAS_NL_IOCLASS_A_MAX (__CAS_NL_IOCLASS_A_MAX - 1)

/**
 * Statistics attributes.
 *
 * Shared by cache, core, and IO class stats nests. All values are raw u64
 * counters (the value field of struct ocf_stat). IO class records do not
 * include error stats.
 */
enum cas_nl_stats_attr {
	CAS_NL_STATS_A_UNSPEC,
	/* Usage (4 KiB units) */
	CAS_NL_STATS_A_USAGE_OCCUPANCY,			/* u64 */
	CAS_NL_STATS_A_USAGE_FREE,			/* u64 */
	CAS_NL_STATS_A_USAGE_CLEAN,			/* u64 */
	CAS_NL_STATS_A_USAGE_DIRTY,			/* u64 */
	/* Requests */
	CAS_NL_STATS_A_REQ_RD_HITS,			/* u64 */
	CAS_NL_STATS_A_REQ_RD_DEFERRED,			/* u64 */
	CAS_NL_STATS_A_REQ_RD_PARTIAL_MISSES,		/* u64 */
	CAS_NL_STATS_A_REQ_RD_FULL_MISSES,		/* u64 */
	CAS_NL_STATS_A_REQ_RD_TOTAL,			/* u64 */
	CAS_NL_STATS_A_REQ_WR_HITS,			/* u64 */
	CAS_NL_STATS_A_REQ_WR_DEFERRED,			/* u64 */
	CAS_NL_STATS_A_REQ_WR_PARTIAL_MISSES,		/* u64 */
	CAS_NL_STATS_A_REQ_WR_FULL_MISSES,		/* u64 */
	CAS_NL_STATS_A_REQ_WR_TOTAL,			/* u64 */
	CAS_NL_STATS_A_REQ_RD_PT,			/* u64 */
	CAS_NL_STATS_A_REQ_WR_PT,			/* u64 */
	CAS_NL_STATS_A_REQ_SERVICED,			/* u64 */
	CAS_NL_STATS_A_REQ_PREFETCH_READAHEAD,		/* u64 */
	CAS_NL_STATS_A_REQ_CLEANER,			/* u64 */
	CAS_NL_STATS_A_REQ_TOTAL,			/* u64 */
	/* Blocks (4 KiB units) */
	CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_RD,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_WR,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_TOTAL,	/* u64 */
	CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_RD,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_WR,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_TOTAL,	/* u64 */
	CAS_NL_STATS_A_BLOCKS_VOLUME_RD,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_VOLUME_WR,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_VOLUME_TOTAL,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_PT_RD,			/* u64 */
	CAS_NL_STATS_A_BLOCKS_PT_WR,			/* u64 */
	CAS_NL_STATS_A_BLOCKS_PT_TOTAL,			/* u64 */
	CAS_NL_STATS_A_BLOCKS_PREFETCH_CORE_RD_READAHEAD,	/* u64 */
	CAS_NL_STATS_A_BLOCKS_PREFETCH_CACHE_WR_READAHEAD,	/* u64 */
	CAS_NL_STATS_A_BLOCKS_CLEANER_CACHE_RD,		/* u64 */
	CAS_NL_STATS_A_BLOCKS_CLEANER_CORE_WR,		/* u64 */
	/* Errors */
	CAS_NL_STATS_A_ERRORS_CORE_VOLUME_RD,		/* u64 */
	CAS_NL_STATS_A_ERRORS_CORE_VOLUME_WR,		/* u64 */
	CAS_NL_STATS_A_ERRORS_CORE_VOLUME_TOTAL,	/* u64 */
	CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_RD,		/* u64 */
	CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_WR,		/* u64 */
	CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_TOTAL,	/* u64 */
	CAS_NL_STATS_A_ERRORS_TOTAL,			/* u64 */
	__CAS_NL_STATS_A_MAX,
};
#define CAS_NL_STATS_A_MAX (__CAS_NL_STATS_A_MAX - 1)

#endif /* CAS_NETLINK_H */
