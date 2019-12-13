/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
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

	/**
	 * eviction policy to be used for newely configured cache instance.
	 */
	ocf_eviction_t eviction_policy;

	uint8_t flush_data; /**< should data be flushed? */

	/**
	 * cache line size
	 */
	ocf_cache_line_size_t line_size;

	uint8_t force; /**< should force option be used? */

	uint64_t min_free_ram; /**< Minimum free RAM memory for cache metadata */

	uint8_t metadata_mode_optimal; /**< Current metadata mode is optimal */

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
	bool force_no_flush; /**< remove core without flushing */
	bool detach; /**< detach core without removing it from cache metadata */

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

	uint8_t metadata_mode; /**< metadata mode (normal/atomic) */

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
		+ OCF_IO_CLASS_MAX * sizeof(struct ocf_io_class_info))

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

/**
 * CAS capabilities.
 */
struct kcas_capabilites {
	uint8_t nvme_format : 1;
		/**< NVMe format support */

	int ext_err_code;
};

struct kcas_upgrade {
	int ext_err_code;
};

/**
 * Format NVMe namespace.
 */
#define CAS_METADATA_MODE_NORMAL	0
#define CAS_METADATA_MODE_ATOMIC	1
#define CAS_METADATA_MODE_INVALID	255

struct kcas_nvme_format {
	char device_path_name[MAX_STR_LEN]; /**< path to NVMe device*/
	int metadata_mode; /**< selected metadata mode */
	int force;

	int ext_err_code;
};

struct kcas_core_pool_remove {
	char core_path_name[MAX_STR_LEN]; /**< path to a core object */

	int ext_err_code;
};

struct kcas_cache_check_device {
	char path_name[MAX_STR_LEN]; /**< path to a device */
	bool is_cache_device;
	bool clean_shutdown;
	bool cache_dirty;
	bool format_atomic;

	int ext_err_code;
};

enum kcas_core_param_id {
	core_param_seq_cutoff_threshold,
	core_param_seq_cutoff_policy,
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
 *    18    *    KCAS_IOCTL_GET_CAPABILITIES                *    OK            *
 *    19    *    KCAS_IOCTL_UPGRADE                         *    OK            *
 *    20    *    KCAS_IOCTL_NVME_FORMAT                     *    OK            *
 *    21    *    KCAS_IOCTL_START_CACHE                     *    OK            *
 *    22    *    KCAS_IOCTL_INSERT_CORE                     *    OK            *
 *    23    *    KCAS_IOCTL_REMOVE_CORE                     *    OK            *
 *    24    *    KCAS_IOCTL_CACHE_INFO                      *    OK            *
 *    25    *    KCAS_IOCTL_CORE_INFO                       *    OK            *
 *    26    *    KCAS_IOCTL_GET_CORE_POOL_COUNT             *    OK            *
 *    27    *    KCAS_IOCTL_GET_CORE_POOL_PATHS             *    OK            *
 *    28    *    KCAS_IOCTL_CORE_POOL_REMOVE                *    OK            *
 *    29    *    KCAS_IOCTL_CACHE_CHECK_DEVICE              *    OK            *
 *    30    *    KCAS_IOCTL_SET_CORE_PARAM                  *    OK            *
 *    31    *    KCAS_IOCTL_GET_CORE_PARAM                  *    OK            *
 *    32    *    KCAS_IOCTL_SET_CACHE_PARAM                 *    OK            *
 *    33    *    KCAS_IOCTL_GET_CACHE_PARAM                 *    OK            *
 *    34    *    KCAS_IOCTL_GET_STATS                       *    OK            *
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

/** Provides capabilites of installed open cas module */
#define KCAS_IOCTL_GET_CAPABILITIES _IOWR(KCAS_IOCTL_MAGIC, 18, struct kcas_capabilites)

/** Start upgrade in flight procedure */
#define KCAS_IOCTL_UPGRADE _IOR(KCAS_IOCTL_MAGIC, 19, struct kcas_upgrade)

/** Format NVMe namespace to support selected metadata mode */
#define KCAS_IOCTL_NVME_FORMAT _IOWR(KCAS_IOCTL_MAGIC, 20, struct kcas_nvme_format)

/** Start new cache instance, load cache or recover cache */
#define KCAS_IOCTL_START_CACHE _IOWR(KCAS_IOCTL_MAGIC, 21, struct kcas_start_cache)

/** Add core object to an running cache instance */
#define KCAS_IOCTL_INSERT_CORE _IOWR(KCAS_IOCTL_MAGIC, 22, struct kcas_insert_core)

/** Remove core object from an running cache instance */
#define KCAS_IOCTL_REMOVE_CORE _IOR(KCAS_IOCTL_MAGIC, 23, struct kcas_remove_core)

/** Retrieve properties of a running cache instance (incl. mode etc.) */
#define KCAS_IOCTL_CACHE_INFO _IOWR(KCAS_IOCTL_MAGIC, 24, struct kcas_cache_info)

/** Rretrieve statisting of a given core object */
#define KCAS_IOCTL_CORE_INFO _IOWR(KCAS_IOCTL_MAGIC, 25, struct kcas_core_info)

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

/**
 * Extended kernel CAS error codes
 */
enum kcas_error {
	/** Must be root */
	KCAS_ERR_ROOT = 2000000,

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

	/** NVMe Cache device contains dirty data. */
	KCAS_ERR_DIRTY_EXISTS_NVME,

	/** Could not create exported object because file in /dev directory
	 * exists
	 */
	KCAS_ERR_FILE_EXISTS,

	/** CAS is under upgrade */
	KCAS_ERR_IN_UPGRADE,

	/** Cache device sector size is greater than core device %s sector size
	 */
	KCAS_ERR_UNALIGNED,

	/** No caches configuration for upgrade in flight */
	KCAS_ERR_NO_STORED_CONF,

	/** Cannot roll-back previous configuration */
	KCAS_ERR_ROLLBACK,

	/** Device is not NVMe */
	KCAS_ERR_NOT_NVME,

	/** Failed to format NVMe device */
	KCAS_ERR_FORMAT_FAILED,

	/** NVMe is formatted to unsupported format */
	KCAS_ERR_NVME_BAD_FORMAT,

	/** Specified LBA format is not supported by the NVMe device */
	KCAS_ERR_UNSUPPORTED_LBA_FORMAT,

	/** Device contains partitions */
	KCAS_ERR_CONTAINS_PART,

	/** Given device is a partition */
	KCAS_ERR_A_PART,

	/** Core has been removed with flush error */
	KCAS_ERR_REMOVED_DIRTY,

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

	/** Waiting for async operation was interrupted*/
	KCAS_ERR_WAITING_INTERRUPTED,
};

#endif
