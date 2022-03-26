/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CAS_LIB_H__
#define __CAS_LIB_H__

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <syslog.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include "safeclib/safe_str_lib.h"
#include <cas_ioctl_codes.h>
#include <sys/utsname.h>

#define CTRL_DEV_PATH "/dev/cas_ctrl"

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))

#define FAILURE 1		/**< default non-zero exit code. */
#define INTERRUPTED 2		/**< if command is interrupted */
#define SUCCESS 0		/**< 0 exit code from majority of our functions \
				     stands for success */

struct core_device {
	int id;
	int cache_id;
	char path[MAX_STR_LEN];
	struct kcas_core_info info;
};

struct cache_device {
	int id;
	int state;
	int expected_core_count;
	char device[MAX_STR_LEN];
	int mode;
	int eviction_policy;
	int cleaning_policy;
	int promotion_policy;
	int dirty;
	int flushed;
	unsigned size;
	int core_count;
	bool standby_detached;
	struct core_device cores[];
};

struct cas_param {
	char *name;
	char *unit;
	char **value_names;
	uint32_t (*transform_value)(uint32_t value);
	uint32_t value;
	bool select;
};

enum output_format_t {
	OUTPUT_FORMAT_INVALID = 0,
	OUTPUT_FORMAT_TABLE = 1,
	OUTPUT_FORMAT_CSV = 2,
	OUTPUT_FORMAT_DEFAULT = OUTPUT_FORMAT_TABLE
};

#define STATS_FILTER_INVALID 0
#define STATS_FILTER_CONF (1 << 0)
#define STATS_FILTER_USAGE  (1 << 1)
#define STATS_FILTER_REQ (1 << 2)
#define STATS_FILTER_BLK (1 << 3)
#define STATS_FILTER_ERR (1 << 4)
#define STATS_FILTER_IOCLASS (1 << 5)
#define STATS_FILTER_ALL (STATS_FILTER_CONF |	\
			  STATS_FILTER_USAGE |	\
			  STATS_FILTER_REQ |	\
			  STATS_FILTER_BLK |	\
			  STATS_FILTER_ERR)
#define STATS_FILTER_DEFAULT STATS_FILTER_ALL

#define STATS_FILTER_COUNTERS (STATS_FILTER_REQ | STATS_FILTER_BLK | STATS_FILTER_ERR)

const char *cleaning_policy_to_name(uint8_t policy);
const char *promotion_policy_to_name(uint8_t policy);
const char *cache_mode_to_name(uint8_t cache_mode);
const char *get_cache_state_name(int cache_state, bool detached);
const char *get_core_state_name(int core_state);
const char *seq_cutoff_policy_to_name(uint8_t seq_cutoff_policy);

__attribute__((format(printf, 2, 3)))
typedef int (*cas_printf_t)(int log_level, const char *format, ...);

extern cas_printf_t cas_printf;

__attribute__((format(printf, 2, 3)))
int caslog(int log_level, const char *template, ...);

#define CAS_CLI_HELP_METADATA_VARIANTS \
	CAS_METADATA_VARIANT_MAX"|" \
	CAS_METADATA_VARIANT_MIX"|" \
	CAS_METADATA_VARIANT_MIN

/* for CLI commands arguments */
#define YES 1
#define NO 0
#define UNDEFINED -1
void metadata_memory_footprint(uint64_t size, float *footprint, const char **units);

int start_cache(uint16_t cache_id, unsigned int cache_init,
		const char *cache_device, ocf_cache_mode_t cache_mode,
		ocf_cache_line_size_t line_size, int force);
int stop_cache(uint16_t cache_id, int flush);

#ifdef WI_AVAILABLE
#define CAS_CLI_HELP_START_CACHE_MODES "wt|wb|wa|pt|wi|wo"
#define CAS_CLI_HELP_SET_CACHE_MODES "wt|wb|wa|pt|wi|wo"
#define CAS_CLI_HELP_SET_CACHE_MODES_FULL "Write-Through, Write-Back, Write-Around, Pass-Through, Write-Invalidate, Write-Only"
#define CAS_CLI_HELP_START_CACHE_MODES_FULL "Write-Through, Write-Back, Write-Around, Pass-Through, Write-Invalidate, Write-Only"
#else
#define CAS_CLI_HELP_START_CACHE_MODES "wt|wb|wa|pt|wo"
#define CAS_CLI_HELP_SET_CACHE_MODES "wt|wb|wa|pt|wo"
#define CAS_CLI_HELP_START_CACHE_MODES_FULL "Write-Through, Write-Back, Write-Around, Pass-Through, Write-Only"
#define CAS_CLI_HELP_SET_CACHE_MODES_FULL "Write-Through, Write-Back, Write-Around, Pass-Through, Write-Only"
#endif

/**
 * @brief handle set cache param command
 * @param cache_id id of cache device
 * @param params parameter array
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */
int cache_params_set(unsigned int cache_id, struct cas_param *params);

/**
 * @brief get cache param value
 * @param cache_id id of cache device
 * @param param_id id of cache parameter to retrive
 * @param param variable to pass value to caller
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */
int cache_get_param(unsigned int cache_id, unsigned int param_id,
		struct cas_param *param);
/**
 * @brief handle get cache param command
 * @param cache_id id of cache device
 * @param params parameter array
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */
int cache_params_get(unsigned int cache_id, struct cas_param *params,
		unsigned int output_format);

/**
 * @brief handle set core param command
 * @param cache_id id of cache device
 * @param core_id id of core device
 * @param params parameter array
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */
int core_params_set(unsigned int cache_id, unsigned int core_id,
		struct cas_param *params);

/**
 * @brief handle get core param command
 * @param cache_id id of cache device
 * @param core_id id of core device
 * @param params parameter array
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */
int core_params_get(unsigned int cache_id, unsigned int core_id,
		struct cas_param *params, unsigned int output_format);

/**
 * @brief handle set cache mode (-Q) command
 * @param in cache mode identifier of cache mode (WRITE_BACK, WRITE_THROUGH etc...)
 * @param cache_id id of cache device
 * @param flush whenever we should flush cache during execution of command. Options: YES, NO, UNDEFINED.
 *              (UNDEFINED is illegal when transitioning from Write-Back mode to any other mode)
 */
int set_cache_mode(unsigned int cache_state, unsigned int cache_id, int flush);

/**
 * @brief add core device to a cache
 *
 * @param cache_id cache to which new core is being added
 * @param core_device path to a core device that is being added
 * @param iogroup_id id of iogroup (this parameter is not exposed in user CLI)
 * @param try_add try add core to earlier loaded cache or add to core pool
 * @param update_path try update path to core device
 * @return 0 upon successful core addition, 1 upon failure
 */
int add_core(unsigned int cache_id, unsigned int core_id, const char *core_device, int try_add, int update_path);

int get_core_info(int fd, int cache_id, int core_id, struct kcas_core_info *info, bool by_id_path);

int remove_core(unsigned int cache_id, unsigned int core_id,
		bool detach, bool force_no_flush);

/**
 * @brief initialize failover standby cache instance
 *
 * @param cache_id cache instance identifier
 * @param line_size cache line size
 * @param cache_device path to caching device
 * @param force discard pre-existing metadata
 *
 * @return 0 upon successful detach, 1 upon failure
 */
int standby_init(int cache_id, ocf_cache_line_size_t line_size,
		const char *cache_device, int force);

/**
 * @brief load failover standby cache instance
 *
 * @param cache_id cache instance identifier
 * @param line_size cache line size
 * @param cache_device path to caching device
 *
 * @return 0 upon successful detach, 1 upon failure
 */
int standby_load(int cache_id, ocf_cache_line_size_t line_size,
		const char *cache_device);

/**
 * @brief detach caching device from failover standby cache instance
 *
 * @param cache_id cache instance identifier
 *
 * @return 0 upon successful detach, 1 upon failure
 */
int standby_detach(int cache_id);

/**
 * @brief activate failover standby cache instance
 *
 * @param cache_id cache instance identifier
 * @param cache_device cache device path
 *
 * @return 0 upon successful detach, 1 upon failure
 */
int standby_activate(int cache_id, const char *cache_device);

void check_cache_state_incomplete(int cache_id, int fd);

/**
 * @brief remove inactive core device from a cache
 *
 * @param cache_id cache from which inactive core is being removed
 * @param cache_id inactive core which is being removed
 * @param force remove inactive force even if it has dirty cache lines assigned
 * @return 0 upon successful core removal, 1 upon failure
 */
int remove_inactive_core(unsigned int cache_id, unsigned int core_id, bool force);

int core_pool_remove(const char *core_device);
int get_core_pool_count(int fd);

int reset_counters(unsigned int cache_id, unsigned int core_id);

int purge_cache(unsigned int cache_id);
int purge_core(unsigned int cache_id, unsigned int core_id);

int flush_cache(unsigned int cache_id);
int flush_core(unsigned int cache_id, unsigned int core_id);

int check_cache_device(const char *device_path);

int partition_list(unsigned int cache_id, unsigned int output_format);
int partition_setup(unsigned int cache_id, const char *file);
int partition_is_name_valid(const char *name);

int cas_module_version(char *buff, int size);
int disk_module_version(char *buff, int size);
int list_caches(unsigned int list_format, bool by_id_path);
int cache_status(unsigned int cache_id, unsigned int core_id, int io_class_id,
		 unsigned int stats_filters, unsigned int stats_format, bool by_id_path);
int get_inactive_core_count(const struct kcas_cache_info *cache_info);

int open_ctrl_device_quiet();
int open_ctrl_device();
int *get_cache_ids(int *cache_count);
struct cache_device *get_cache_device_by_id_fd(int cache_id, int fd, bool by_id_path);
struct cache_device **get_cache_devices(int *caches_count, bool by_id_path);
void free_cache_devices_list(struct cache_device **caches, int caches_count);

int validate_dev(const char *dev_path);
int validate_str_num(const char *source_str, const char *msg, long long int min, long long int max);
int validate_str_num_sbd(const char *source_str, const char *msg, int min, int max);
int validate_str_unum(const char *source_str, const char *msg, unsigned int min,
		unsigned int max);
int validate_path(const char *path, int exist);

int validate_str_cache_mode(const char *s);
int validate_str_cln_policy(const char *s);
int validate_str_promotion_policy(const char *s);
int validate_str_stats_filters(const char* s);
int validate_str_output_format(const char* s);

/**
 * @brief clear metadata
 *
 * @param[in] cache_device device to which zeroing cache's metadata applies
 * @param[in] force enforce metadata erasure despite dirty data, metadata
 * 		mistmatch and/or dirty shutdown
 * @return 0 if succeed, 1 if failed
 */
int zero_md(const char *cache_device, bool force);

/**
 * @brief calculate flush progress
 *
 * @param[in] dirty number of dirty blocks
 * @param[in] flush number of flushed blocks
 * @return flush progress or 0 if no flush is ongoing
 */
float calculate_flush_progress(unsigned dirty, unsigned flushed);

/**
 * @brief calculate flush progress of given cache
 *
 * @param[in] cache_id cache to which calculation applies
 * @param[out] progress flush progress
 * @return 0 on success, nonzero on failure
 */
int get_flush_progress(int unsigned cache_id, float *progress);

/**
 * @brief print error message corresponding with CAS extended error code.
 */
void print_err(int error_code);

/**
  * @brief get special device file path (/dev/sdX) for disk.
  */
int get_dev_path(const char* disk, char* buf, size_t num);

/**
 * @brief make sure device link is unique and write sanitized version to \a dest_path
 *
 * @param[in] src_path link to device
 * @param[in] src_len length of \a src_path
 * @param[in] dest_len max length of \a dest_path
 * @param[out] dest_path sanitized absolute path
 * @return 0 on success, nonzero on failure
 */
int set_device_path(char *dest_path, size_t dest_len, const char *src_path, size_t src_len);

/**
 * @brief convert string to int
 */
bool str_to_int(const char* start, char** end, int *val);

#endif
