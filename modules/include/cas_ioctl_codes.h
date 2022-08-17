/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CAS_IOCTL_CODES_H__
#define __CAS_IOCTL_CODES_H__
/**
 * @file
 * @brief Main file for ioctl interface between kernel module and userspace component.
 *
 * This file contains IOCTL commands, structured passed as parameters to said commands
 * and documentation of CAS specific extended error codes (that are a bit more verbose than
 * standard errno)
 */

#include "ocf/ocf.h"
#include <linux/limits.h>
#include <linux/ioctl.h>

/**
 * Max path, string size
 */
#define MAX_STR_LEN PATH_MAX

/**
 * Max size of elevator name (including null terminator)
 */
#define MAX_ELEVATOR_NAME 16

/** \cond SKIP_IN_DOC */
#define CACHE_LIST_ID_LIMIT 20

#define INVALID_FLUSH_PARAM -1
/** \endcond */

#define CACHE_INIT_NEW	0 /**< initialize new metadata from fresh start */
#define CACHE_INIT_LOAD	1 /**< load existing metadata */
#define CACHE_INIT_STANDBY_NEW 2 /**< initialize failover standby cache */
#define CACHE_INIT_STANDBY_LOAD 3 /**< load failover standby cache */

struct kcas_start_cache {
	/**
	 * id of newely inserted cache (in range 1-OCF_CACHE_ID_MAX).
	 */
	uint16_t cache_id;

	/**
	 * cache initialization mode
	 * valid choices are:
	 * * CACHE_INIT_NEW
	 * * CACHE_INIT_LOAD
	 */
	uint8_t init_cache;

	char cache_path_name[MAX_STR_LEN]; /**< path to an ssd*/

	/**
	 * caching mode for new cache instance
	 * valid choices are:
	 * * WRITE_THROUGH
	 * * WRITE_BACK
	 * * WRITE_AROUND
	 * * PASS_THROUGH
	 */
	ocf_cache_mode_t caching_mode;

	uint8_t flush_data; /**< should data be flushed? */

	/**
	 * cache line size
	 */
	ocf_cache_line_size_t line_size;

	uint8_t force; /**< should force option be used? */

	uint64_t min_free_ram; /**< Minimum free RAM memory for cache metadata */

	char cache_elevator[MAX_ELEVATOR_NAME];

	int ext_err_code;
};

struct kcas_stop_cache {
	uint16_t cache_id; /**< id of cache to be stopped */

	uint8_t flush_data; /**< should data be flushed? */

	int ext_err_code;
};

struct kcas_set_cache_state {
	uint16_t cache_id; /**< id of cache for which state should be set */

	ocf_cache_mode_t caching_mode;

	uint8_t flush_data; /**< should data be flushed? */

	int ext_err_code;
};

struct kcas_insert_core {
	uint16_t cache_id; /**< id of an running cache */
	uint16_t core_id; /**< id of newely inserted core object */
	char core_path_name[MAX_STR_LEN]; /**< path to a core object */
	bool try_add; /**< add core to pool if cache isn't present */
	bool update_path; /**< provide alternative path for core device */

	int ext_err_code;
};

struct kcas_remove_core {
	uint16_t cache_id; /**< id of an running cache */
	uint16_t core_id; /**< id core object to be removed */
	bool force_no_flush; /**< remove active core without flushing */
	bool detach; /**< detach core without removing it from cache metadata */

	int ext_err_code;
};

struct kcas_remove_inactive {
	uint16_t cache_id; /**< id of an running cache */
	uint16_t core_id; /**< id core object to be removed */
	bool force; /**< remove inactive core without flushing */

	int ext_err_code;
};

struct kcas_reset_stats {
	uint16_t cache_id; /**< id of an running cache */
	uint16_t core_id; /**< id core object to be removed */

	int ext_err_code;
};

struct kcas_flush_cache {
	uint16_t cache_id; /**< id of an running cache */

	int ext_err_code;
};

struct kcas_interrupt_flushing {
	uint16_t cache_id; /**< id of an running cache */

	int ext_err_code;
};

struct kcas_flush_core {
	uint16_t cache_id; /**< id of an running cache */
	uint16_t core_id; /**< id core object to be removed */

	int ext_err_code;
};

struct kcas_get_stats {
	/** id of a cache */
	uint16_t cache_id;

	/** id of a core */
	uint16_t core_id;

	/** id of an ioclass */
	uint16_t part_id;

	/** fields to be filled with statistics */
	struct ocf_stats_usage usage;

	struct ocf_stats_requests req;

	struct ocf_stats_blocks blocks;

	struct ocf_stats_errors errors;

	int ext_err_code;
};

struct kcas_cache_info {
	/** id of a cache */
	uint16_t cache_id;

	/** path to caching device */
	char cache_path_name[MAX_STR_LEN];

	/**
	 * IDs of cores associated with this cache.
	 */
	uint16_t core_id[OCF_CORE_MAX];

	struct ocf_cache_info info;

	int ext_err_code;
};

struct kcas_core_info {
	/** Path name to underlying device */
	char core_path_name[MAX_STR_LEN];

	/** Cache id */
	uint16_t cache_id;

	/** Core id */
	uint16_t core_id;

	struct ocf_core_info info;

	ocf_core_state_t state;

	bool exp_obj_exists;

	int ext_err_code;
};

struct kcas_core_pool_path {
	/** Handler to tab with cores path*/
	char *core_path_tab;

	/** Number of cores in core pool */
	int core_pool_count;

	int ext_err_code;
};

struct kcas_cache_count {
	/** Number of running caches */
	int cache_count;

	int ext_err_code;
};

struct kcas_core_pool_count {
	/** Number of cores in core pool */
	int core_pool_count;

	int ext_err_code;
};

/**
 * IO class info and statistics
 */
struct kcas_io_class {
	/** Cache ID */
	uint16_t cache_id;

	/** IO class id for which info will be retrieved */
	uint32_t class_id;

	/** IO class info */
	struct ocf_io_class_info info;

	int ext_err_code;
};

/**
 * IO class settings
 */
struct kcas_io_classes {
	/** Cache ID */
	uint16_t cache_id;

	int ext_err_code;

	/** IO class info */
	struct ocf_io_class_info info[];
};

#define KCAS_IO_CLASSES_SIZE (sizeof(struct kcas_io_classes) \
		+ OCF_USER_IO_CLASS_MAX * sizeof(struct ocf_io_class_info))

/**
 * structure in which result of KCAS_IOCTL_LIST_CACHE is supplied from kernel module.
 */
struct kcas_cache_list {
	/** starting position in dev list for getting cache id */
	uint32_t id_position;
	/** requested number of ids and returned in response cmd */
	uint32_t in_out_num;
	/** array with cache list and its properties */
	uint16_t cache_id_tab[CACHE_LIST_ID_LIMIT];

	int ext_err_code;
};

struct kcas_core_pool_remove {
	char core_path_name[MAX_STR_LEN]; /**< path to a core object */

	int ext_err_code;
};

struct kcas_cache_check_device {
	char path_name[MAX_STR_LEN]; /**< path to a device */
	bool is_cache_device; /* OCF metadata detected */

	/* following bool flags are defined is_cache_device == 1 */
	bool metadata_compatible; /* OCF metadata is in current version */

	/* following bool flags are defined iff is_metadata_compatible == 1 */
	bool clean_shutdown;
	bool cache_dirty;

	int ext_err_code;
};

enum kcas_core_param_id {
	core_param_seq_cutoff_threshold,
	core_param_seq_cutoff_policy,
	core_param_seq_cutoff_promotion_count,
	core_param_id_max,
};

struct kcas_set_core_param {
	uint16_t cache_id;
	uint16_t core_id;
	enum kcas_core_param_id param_id;
	uint32_t param_value;

	int ext_err_code;
};

struct kcas_get_core_param {
	uint16_t cache_id;
	uint16_t core_id;
	enum kcas_core_param_id param_id;
	uint32_t param_value;

	int ext_err_code;
};

enum kcas_cache_param_id {
	cache_param_cleaning_policy_type,
	cache_param_cleaning_alru_wake_up_time,
	cache_param_cleaning_alru_stale_buffer_time,
	cache_param_cleaning_alru_flush_max_buffers,
	cache_param_cleaning_alru_activity_threshold,
	cache_param_cleaning_acp_wake_up_time,
	cache_param_cleaning_acp_flush_max_buffers,
	cache_param_promotion_policy_type,
	cache_param_promotion_nhit_insertion_threshold,
	cache_param_promotion_nhit_trigger_threshold,
	cache_param_id_max,
};

struct kcas_set_cache_param {
	uint16_t cache_id;
	enum kcas_cache_param_id param_id;
	uint32_t param_value;

	int ext_err_code;
};

struct kcas_get_cache_param {
	uint16_t cache_id;
	enum kcas_cache_param_id param_id;
	uint32_t param_value;

	int ext_err_code;
};

struct kcas_standby_detach
{
	uint16_t cache_id;

	int ext_err_code;
};

struct kcas_standby_activate
{
	uint16_t cache_id;
	char cache_path[MAX_STR_LEN]; /**< path to an ssd*/

	int ext_err_code;
};

/*******************************************************************************
 *   CODE   *              NAME             *               STATUS             *
 *******************************************************************************
 *     1    *    KCAS_IOCTL_START_CACHE                     *    DEPRECATED    *
 *     2    *    KCAS_IOCTL_STOP_CACHE                      *    OK            *
 *     3    *    KCAS_IOCTL_SET_CACHE_STATE                 *    OK            *
 *     4    *    KCAS_IOCTL_INSERT_CORE                     *    DEPRECATED    *
 *     5    *    KCAS_IOCTL_REMOVE_CORE                     *    DEPRECATED    *
 *     6    *    KCAS_IOCTL_RESET_STATS                     *    OK            *
 *     9    *    KCAS_IOCTL_FLUSH_CACHE                     *    OK            *
 *    10    *    KCAS_IOCTL_INTERRUPT_FLUSHING              *    OK            *
 *    11    *    KCAS_IOCTL_FLUSH_CORE                      *    OK            *
 *    12    *    KCAS_IOCTL_CACHE_INFO                      *    DEPRECATED    *
 *    13    *    KCAS_IOCTL_CORE_INFO                       *    DEPRECATED    *
 *    14    *    KCAS_IOCTL_PARTITION_INFO                  *    OK            *
 *    15    *    KCAS_IOCTL_PARTITION_SET                   *    OK            *
 *    16    *    KCAS_IOCTL_GET_CACHE_COUNT                 *    OK            *
 *    17    *    KCAS_IOCTL_LIST_CACHE                      *    OK            *
 *    18    *    KCAS_IOCTL_GET_CAPABILITIES                *    DEPRECATED    *
 *    19    *    KCAS_IOCTL_UPGRADE                         *    DEPRACATED    *
 *    20    *    KCAS_IOCTL_NVME_FORMAT                     *    DEPRECATED    *
 *    21    *    KCAS_IOCTL_START_CACHE                     *    OK            *
 *    22    *    KCAS_IOCTL_INSERT_CORE                     *    OK            *
 *    23    *    KCAS_IOCTL_REMOVE_CORE                     *    OK            *
 *    24    *    KCAS_IOCTL_CACHE_INFO                      *    OK            *
 *    25    *    KCAS_IOCTL_CORE_INFO                       *    DEPERCATED    *
 *    26    *    KCAS_IOCTL_GET_CORE_POOL_COUNT             *    OK            *
 *    27    *    KCAS_IOCTL_GET_CORE_POOL_PATHS             *    OK            *
 *    28    *    KCAS_IOCTL_CORE_POOL_REMOVE                *    OK            *
 *    29    *    KCAS_IOCTL_CACHE_CHECK_DEVICE              *    OK            *
 *    30    *    KCAS_IOCTL_SET_CORE_PARAM                  *    OK            *
 *    31    *    KCAS_IOCTL_GET_CORE_PARAM                  *    OK            *
 *    32    *    KCAS_IOCTL_SET_CACHE_PARAM                 *    OK            *
 *    33    *    KCAS_IOCTL_GET_CACHE_PARAM                 *    OK            *
 *    34    *    KCAS_IOCTL_GET_STATS                       *    OK            *
 *    35    *    KCAS_IOCTL_PURGE_CACHE                     *    OK            *
 *    36    *    KCAS_IOCTL_PURGE_CORE                      *    OK            *
 *    37    *    KCAS_IOCTL_REMOVE_INACTIVE                 *    OK            *
 *    38    *    KCAS_IOCTL_STANDBY_DETACH                  *    OK            *
 *    39    *    KCAS_IOCTL_STANDBY_ACTIVATE                *    OK            *
 *    40    *    KCAS_IOCTL_CORE_INFO                       *    OK            *
 *******************************************************************************
 */

/** \cond SKIP_IN_DOC */
#define KCAS_IOCTL_MAGIC (0xBA)
/** \endcond */

/** Stop cache with or without flushing dirty data */
#define KCAS_IOCTL_STOP_CACHE _IOWR(KCAS_IOCTL_MAGIC, 2, struct kcas_stop_cache)

/** Set cache mode (write back, write through etc... */
#define KCAS_IOCTL_SET_CACHE_STATE _IOR(KCAS_IOCTL_MAGIC, 3, struct kcas_set_cache_state)

/** Reset statistic counters for given cache object */
#define KCAS_IOCTL_RESET_STATS _IOR(KCAS_IOCTL_MAGIC, 6, struct kcas_reset_stats)

/** Flush dirty data from an running cache instance that
 *  is or was running in write-back mode */
#define KCAS_IOCTL_FLUSH_CACHE _IOWR(KCAS_IOCTL_MAGIC, 9, struct kcas_flush_cache)

/** Interrupt dirty block flushing operation */
#define KCAS_IOCTL_INTERRUPT_FLUSHING _IOWR(KCAS_IOCTL_MAGIC, 10, struct kcas_interrupt_flushing)

/* Flush dirty data from an running core object
 * that is or was running in write-back mode */
#define KCAS_IOCTL_FLUSH_CORE _IOR(KCAS_IOCTL_MAGIC, 11, struct kcas_flush_core)

/** Retrieving partition status for specified cache id and partition id */
#define KCAS_IOCTL_PARTITION_INFO _IOWR(KCAS_IOCTL_MAGIC, 14, struct kcas_io_class)

/** Configure partitions for specified cache id */
#define KCAS_IOCTL_PARTITION_SET _IOWR(KCAS_IOCTL_MAGIC, 15, struct kcas_io_classes)

/** Obtain number of valid cache ids within running open cas instance */
#define KCAS_IOCTL_GET_CACHE_COUNT _IOR(KCAS_IOCTL_MAGIC, 16, struct kcas_cache_count)

/** List valid cache ids within Open CAS module */
#define KCAS_IOCTL_LIST_CACHE _IOWR(KCAS_IOCTL_MAGIC, 17, struct kcas_cache_list)

/** Start new cache instance, load cache or recover cache */
#define KCAS_IOCTL_START_CACHE _IOWR(KCAS_IOCTL_MAGIC, 21, struct kcas_start_cache)

/** Add core object to an running cache instance */
#define KCAS_IOCTL_INSERT_CORE _IOWR(KCAS_IOCTL_MAGIC, 22, struct kcas_insert_core)

/** Remove active core object from an running cache instance */
#define KCAS_IOCTL_REMOVE_CORE _IOR(KCAS_IOCTL_MAGIC, 23, struct kcas_remove_core)

/** Retrieve properties of a running cache instance (incl. mode etc.) */
#define KCAS_IOCTL_CACHE_INFO _IOWR(KCAS_IOCTL_MAGIC, 24, struct kcas_cache_info)

/** Get core pool count */
#define KCAS_IOCTL_GET_CORE_POOL_COUNT _IOR(KCAS_IOCTL_MAGIC, 26, struct kcas_core_pool_count)

/** Ret paths from devices which are in core pool */
#define KCAS_IOCTL_GET_CORE_POOL_PATHS _IOWR(KCAS_IOCTL_MAGIC, 27, struct kcas_core_pool_path)

/** Remove device from core pool */
#define KCAS_IOCTL_CORE_POOL_REMOVE _IOWR(KCAS_IOCTL_MAGIC, 28, struct kcas_core_pool_remove)

/** Check if given device is initialized cache device */
#define KCAS_IOCTL_CACHE_CHECK_DEVICE _IOWR(KCAS_IOCTL_MAGIC, 29, struct kcas_cache_check_device)

/** Set various core runtime parameters */
#define KCAS_IOCTL_SET_CORE_PARAM _IOW(KCAS_IOCTL_MAGIC, 30, struct kcas_set_core_param)

/** Get various core runtime parameters */
#define KCAS_IOCTL_GET_CORE_PARAM _IOW(KCAS_IOCTL_MAGIC, 31, struct kcas_get_core_param)

/** Set various cache runtime parameters */
#define KCAS_IOCTL_SET_CACHE_PARAM _IOW(KCAS_IOCTL_MAGIC, 32, struct kcas_set_cache_param)

/** Get various cache runtime parameters */
#define KCAS_IOCTL_GET_CACHE_PARAM _IOW(KCAS_IOCTL_MAGIC, 33, struct kcas_get_cache_param)

/** Get stats of particular OCF object */
#define KCAS_IOCTL_GET_STATS _IOR(KCAS_IOCTL_MAGIC, 34, struct kcas_get_stats)

/* Flush dirty data from running cache
 * and invalidate all valid cache lines */
#define KCAS_IOCTL_PURGE_CACHE _IOWR(KCAS_IOCTL_MAGIC, 35, struct kcas_flush_cache)

/* Flush dirty data from running core object
 * and invalidate all valid cache lines associated with given core. */
#define KCAS_IOCTL_PURGE_CORE _IOWR(KCAS_IOCTL_MAGIC, 36, struct kcas_flush_core)

/** Remove inactive core object from an running cache instance */
#define KCAS_IOCTL_REMOVE_INACTIVE _IOWR(KCAS_IOCTL_MAGIC, 37, struct kcas_remove_inactive)

/** Detach caching drive from failover standby cache instance */
#define KCAS_IOCTL_STANDBY_DETACH _IOWR(KCAS_IOCTL_MAGIC, 38, struct kcas_standby_detach)

/** Activate failover standby cache instance */
#define KCAS_IOCTL_STANDBY_ACTIVATE _IOWR(KCAS_IOCTL_MAGIC, 39, struct kcas_standby_activate)

/** Rretrieve statisting of a given core object */
#define KCAS_IOCTL_CORE_INFO _IOWR(KCAS_IOCTL_MAGIC, 40, struct kcas_core_info)

/**
 * Extended kernel CAS error codes
 */
enum kcas_error {
	KCAS_ERR_MIN = 2000000,

	/** Must be root */
	KCAS_ERR_ROOT = KCAS_ERR_MIN,

	/** System Error */
	KCAS_ERR_SYSTEM,

	/** Range parameters are invalid */
	KCAS_ERR_BAD_RANGE,

	/** Illegal range, out of device space */
	KCAS_ERR_DEV_SPACE,

	/** Invalid ioctl */
	KCAS_ERR_INV_IOCTL,

	/** Device opens or mount are pending to this cache */
	KCAS_ERR_DEV_PENDING,

	/** Could not create exported object because file in /dev directory
	 * exists
	 */
	KCAS_ERR_FILE_EXISTS,

	/** Cache device sector size is greater than core device %s sector size
	 */
	KCAS_ERR_UNALIGNED,

	/** Cannot roll-back previous configuration */
	KCAS_ERR_ROLLBACK,

	/** NVMe is formatted to unsupported format */
	KCAS_ERR_NVME_BAD_FORMAT,

	/** Device contains partitions */
	KCAS_ERR_CONTAINS_PART,

	/** Given device is a partition */
	KCAS_ERR_A_PART,

	/** Removing core failed and rollback failed too */
	KCAS_ERR_DETACHED,

	/** Cache is already in standby detached state */
	KCAS_ERR_STANDBY_DETACHED,

	/** Cache has been stopped, but it may contain dirty data */
	KCAS_ERR_STOPPED_DIRTY,

	/** Core pool is not empty */
	KCAS_ERR_CORE_POOL_NOT_EMPTY,

	/** No caching device is attached */
	KCAS_ERR_NO_CACHE_ATTACHED,

	/** Invalid syntax of classification rule */
	KCAS_ERR_CLS_RULE_INVALID_SYNTAX,

	/** Condition token does not identify any known condition */
	KCAS_ERR_CLS_RULE_UNKNOWN_CONDITION,

	/** Waiting for async operation was interrupted */
	KCAS_ERR_WAITING_INTERRUPTED,

	/** Core device is in active state */
	KCAS_ERR_CORE_IN_ACTIVE_STATE,

	/** Inactive core has dirty data assigned */
	KCAS_ERR_INACTIVE_CORE_IS_DIRTY,

	KCAS_ERR_MAX = KCAS_ERR_INACTIVE_CORE_IS_DIRTY,
};

#endif
