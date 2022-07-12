/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdio.h>
#include <errno.h>
#include <assert.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <inttypes.h>
#include <limits.h>
#include <fstab.h>
#include <linux/fs.h>
#include <linux/types.h>
#include <linux/major.h>
#include <mntent.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <time.h>
#include <pthread.h>
#include <dirent.h>
#include <stdbool.h>
#include "cas_lib.h"
#include "extended_err_msg.h"
#include "cas_lib_utils.h"
#include "csvparse.h"
#include "statistics_view.h"
#include "safeclib/safe_mem_lib.h"
#include "safeclib/safe_str_lib.h"
#include "safeclib/safe_lib.h"
#include <cas_ioctl_codes.h>
#include "psort.h"
#include <libgen.h>
#include <regex.h>
#include <math.h>

#define PRINT_STAT(x) header->cmd_input.cache_stats.x

#define CORE_ADD_MAX_TIMEOUT 30

#define CHECK_IF_CACHE_IS_MOUNTED -1

/**
 * @brief Routine verifies if filesystem is currently mounted for given cache/core
 *
 *        If FAILURE is returned, reason for failure is printed onto
 *        standard error.
 * @param cache_id cache id of filesystem (to verify if it is mounted)
 * @param core_id core id of filesystem (to verify if it is mounted); if this
 *        parameter is set to negative value, it is only checked if any core belonging
 *        to given cache is mounted;
 * @return SUCCESS if is not mounted; FAILURE if filesystem is mounted
 */
int check_if_mounted(int cache_id, int core_id);

/* KCAS_IOCTL_CACHE_CHECK_DEVICE  wrapper */
int _check_cache_device(const char *device_path,
		struct kcas_cache_check_device *cmd_info);

static const char *cache_states_name[ocf_cache_state_max + 1] = {
		[ocf_cache_state_running] = "Running",
		[ocf_cache_state_stopping] = "Stopping",
		[ocf_cache_state_initializing] = "Initializing",
		[ocf_cache_state_incomplete] = "Incomplete",
		[ocf_cache_state_standby] = "Standby",
		[ocf_cache_state_max] = "Unknown",
};

static const char *core_states_name[] = {
		[ocf_core_state_active] = "Active",
		[ocf_core_state_inactive] = "Inactive",
};

#define NOT_RUNNING_STATE "Not running"

#define STANDBY_DETACHED_STATE "Standby detached"

#define CACHE_STATE_LENGHT 20

#define CAS_LOG_FILE "/var/log/opencas.log"
#define CAS_LOG_LEVEL LOG_INFO

int vcaslog(int log_level, const char *template, va_list args)
{
	FILE *log;
	time_t t;
	struct tm *tm;
	char *timestamp;
	int ret;

	if (log_level > CAS_LOG_LEVEL)
		return 0;

	log = fopen(CAS_LOG_FILE, "a");
	if (!log)
		return FAILURE;

	ret = lockf(fileno(log), F_LOCK, 0);
	if (ret < 0)
		goto out;

	t = time(NULL);
	tm = localtime(&t);
	if (!tm) {
		ret = FAILURE;
		goto out;
	}

	timestamp = asctime(tm);
	if (!timestamp) {
		ret = FAILURE;
		goto out;
	}

	fseek(log, 0, SEEK_END);
	fprintf(log, "%s casadm: ", timestamp);
	vfprintf(log, template, args);
	fflush(log);

	lockf(fileno(log), F_ULOCK, 0);

out:
	fclose(log);
	return ret;
}

__attribute__((format(printf, 2, 3)))
int caslog(int log_level, const char *template, ...)
{
	va_list args;
	va_start(args, template);
	vcaslog(log_level, template, args);
	va_end(args);
	return 0;
}

__attribute__((format(printf, 2, 3)))
int std_printf(int log_level, const char *template, ...)
{
	va_list args;
	va_start(args, template);
	if (LOG_WARNING >= log_level) {
		va_list args_copy;
		va_copy(args_copy, args);
		vfprintf(stderr, template, args);
		vcaslog(log_level, template, args_copy);
		va_end(args_copy);
	} else {
		vfprintf(stdout, template, args);
	}
	va_end(args);
	return 0;
}

cas_printf_t cas_printf = std_printf;

int validate_dev(const char *dev_path)
{
	struct fstab *fstab_entry;
	struct stat status;

	fstab_entry = getfsspec(dev_path);
	if (fstab_entry != NULL) {
		printf("Device entry present in fstab, please remove it.\n");
		return FAILURE;
	}

	if (stat(dev_path, &status) == -1) {
		printf("Failed to query device status.\n");
		return FAILURE;
	}

	if (!S_ISBLK(status.st_mode)) {
		printf("Path does not describe a block device\n");
		return FAILURE;
	}

	return SUCCESS;
}

int validate_path(const char *path, int exist)
{
	if (NULL == path) {
		return FAILURE;
	}

	if (0 == path[0]) {
		cas_printf(LOG_ERR, "Empty path\n");
		return FAILURE;
	}

	if (strnlen(path, MAX_STR_LEN) >= MAX_STR_LEN) {
		cas_printf(LOG_ERR, "File path too long\n");
		return FAILURE;
	}

	if (exist) {
		struct stat _stat = { 0 };
		int result = stat(path, &_stat);
		if (result) {
			cas_printf(LOG_ERR, "File does not exist\n");
			return FAILURE;
		}
	}

	return SUCCESS;
}

int __validate_str_num(const char *source_str, const char *msg,
		long long int min, long long int max, bool validate_sbd)
{
	uint64_t ret;
	char *endptr = NULL;

	errno = 0;
	ret = strtoul(source_str, &endptr, 10);
	if (endptr == source_str || (endptr && *endptr != '\0') ||
			((ret == 0 || ret == ULONG_MAX) && errno)) {
		cas_printf(LOG_ERR, "Invalid %s, must be a correct unsigned decimal integer.\n",
			   msg);
		return FAILURE;
	} else if (ret < min || ret > max) {
		cas_printf(LOG_ERR, "Invalid %s, must be in the range %lld-%lld.\n",
			   msg, min, max);
		return FAILURE;
	} else if (validate_sbd && __builtin_popcount(ret) != 1) {
		cas_printf(LOG_ERR, "Invalid %s, must be a power of 2.\n", msg);
		return FAILURE;
	}

	return SUCCESS;
}

int validate_str_num(const char *source_str, const char *msg, long long int min, long long int max)
{
	return __validate_str_num(source_str, msg, min, max, false);
}

int validate_str_num_sbd(const char *source_str, const char *msg, int min, int max)
{
	return __validate_str_num(source_str, msg, min, max, true);
}

int validate_str_unum(const char *source_str, const char *msg, unsigned int min,
		unsigned int max)
{
	return __validate_str_num(source_str, msg, min, max, false);
}

struct name_to_val_mapping {
	const char* short_name;
	const char* long_name;
	int value;
};

static struct name_to_val_mapping cache_mode_names[] = {
	{ .short_name = "wt", .long_name = "Write-Through", .value = ocf_cache_mode_wt },
	{ .short_name = "wb", .long_name = "Write-Back", .value = ocf_cache_mode_wb },
	{ .short_name = "wa", .long_name = "Write-Around", .value = ocf_cache_mode_wa },
	{ .short_name = "pt", .long_name = "Pass-Through", .value = ocf_cache_mode_pt },
#ifdef WI_AVAILABLE
	{ .short_name = "wi", .long_name = "Write-Invalidate", .value = ocf_cache_mode_wi },
#endif
	{ .short_name = "wo", .long_name = "Write-Only", .value = ocf_cache_mode_wo },
	{ NULL }
};

static struct name_to_val_mapping cleaning_policy_names[] = {
	{ .short_name = "nop", .value = ocf_cleaning_nop },
	{ .short_name = "alru", .value = ocf_cleaning_alru },
	{ .short_name = "acp", .value = ocf_cleaning_acp },
	{ NULL }
};

static struct name_to_val_mapping promotion_policy_names[] = {
	{ .short_name = "always", .value = ocf_promotion_always },
	{ .short_name = "nhit", .value = ocf_promotion_nhit },
	{ NULL}
};

static struct name_to_val_mapping seq_cutoff_policy_names[] = {
	{ .short_name = "always", .value = ocf_seq_cutoff_policy_always },
	{ .short_name = "full", .value = ocf_seq_cutoff_policy_full },
	{ .short_name = "never", .value = ocf_seq_cutoff_policy_never },
	{ NULL }
};

static struct name_to_val_mapping stats_filters_names[] = {
	{ .short_name = "conf", .value = STATS_FILTER_CONF },
	{ .short_name = "usage", .value = STATS_FILTER_USAGE },
	{ .short_name = "req", .value = STATS_FILTER_REQ },
	{ .short_name = "blk", .value = STATS_FILTER_BLK },
	{ .short_name = "err", .value = STATS_FILTER_ERR },
	{ .short_name = "all", .value = STATS_FILTER_ALL },
	{ NULL }
};

static struct name_to_val_mapping output_formats_names[] = {
	{ .short_name = "table", .value = OUTPUT_FORMAT_TABLE },
	{ .short_name = "csv", .value = OUTPUT_FORMAT_CSV },
	{ NULL }
};

static int validate_str_val_mapping(const char* s,
				    const struct name_to_val_mapping* mappings,
				    int invalid_value)
{
	int i;

	if (strempty(s)) {
		return invalid_value;
	}

	for (i = 0; NULL != mappings[i].short_name; ++i) {
		if (0 == strncmp(mappings[i].short_name, s, MAX_STR_LEN)) {
			return mappings[i].value;
		}
	}

	return invalid_value;
}

static int validate_str_val_mapping_multi(const char* s,
					  const struct name_to_val_mapping* mappings,
					  int invalid_value)
{
	const char* p;
	char* token;
	char* delim;
	int value = 0;
	int token_val;

	if (strempty(s)) {
		return invalid_value;
	}

	p = s;
	while (p[0]) {
		delim = strchr(p, ',');
		if (delim == p) {
			/* Empty tokens not allowed */
			return invalid_value;
		}

		if (delim) {
			token = strndup(p, delim - p);
			/* Skip token and comma */
			p = delim + 1;
			if (!p[0]) {
				/* Trailing comma not allowed */
				free(token);
				return invalid_value;
			}
		} else {
			size_t len = strnlen(p, MAX_STR_LEN);
			if (len >= MAX_STR_LEN) {
				return invalid_value;
			}

			token = strdup(p);
			p += len;
		}

		token_val = validate_str_val_mapping(token, mappings, invalid_value);
		if (token_val == invalid_value) {
			free(token);
			return invalid_value;
		}

		value |= token_val;
		free(token);
	}
	return value;
}

static const char* val_to_long_name(int value, const struct name_to_val_mapping* mappings,
			    const char* other_name)
{
	int i;
	for (i = 0; NULL != mappings[i].long_name; ++i) {
		if (mappings[i].value == value) {
			return mappings[i].long_name;
		}
	}
	return other_name;
}

static const char* val_to_short_name(int value, const struct name_to_val_mapping* mappings,
			     const char* other_name)
{
	int i;
	for (i = 0; NULL != mappings[i].short_name; ++i) {
		if (mappings[i].value == value) {
			return mappings[i].short_name;
		}
	}
	return other_name;
}

inline const char *cache_mode_to_name(uint8_t cache_mode)
{
	return val_to_short_name(cache_mode, cache_mode_names, "Unknown");
}

static inline const char *cache_mode_to_name_long(uint8_t cache_mode)
{
	return val_to_long_name(cache_mode, cache_mode_names, "??");
}

inline int validate_str_cache_mode(const char *s)
{
	return validate_str_val_mapping(s, cache_mode_names, -1);
}

inline int validate_str_cln_policy(const char *s)
{
	return validate_str_val_mapping(s, cleaning_policy_names, -1);
}

inline const char *cleaning_policy_to_name(uint8_t policy)
{
	return val_to_short_name(policy, cleaning_policy_names, "Unknown");
}

inline int validate_str_promotion_policy(const char *s)
{
	return validate_str_val_mapping(s, promotion_policy_names, -1);
}

inline const char *promotion_policy_to_name(uint8_t policy)
{
	return val_to_short_name(policy, promotion_policy_names, "Unknown");
}

const char *seq_cutoff_policy_to_name(uint8_t seq_cutoff_policy)
{
	return val_to_short_name(seq_cutoff_policy,
			seq_cutoff_policy_names, "Invalid");
}

inline void metadata_memory_footprint(uint64_t size, float *footprint,
	const char **units)
{
	float factor = 1;
	static const char *units_names[] = {"B", "KiB", "MiB", "GiB", "TiB"};
	uint32_t i;

	for (i = 0; i < sizeof(units_names) / sizeof(units_names[0]); i++) {
		*footprint = ((float) (size)) / factor;
		*units = units_names[i];

		if (*footprint < 1024.0) {
			break;
		}

		factor *= 1024;
	}
}

/* Returns one of or combination of STATS_FILTER values
 * or STATS_FILTER_INVALID in case of error.
 */
int validate_str_stats_filters(const char* s)
{
	return validate_str_val_mapping_multi(s, stats_filters_names,
					      STATS_FILTER_INVALID);
}

/* Returns one of OUTPUT_FORMAT values
 * or OUTPUT_FORMAT_INVALID in case of error.
 */
int validate_str_output_format(const char* s)
{
	return validate_str_val_mapping(s, output_formats_names,
					OUTPUT_FORMAT_INVALID);
}

void print_err(int error_code)
{
	const char *msg = cas_strerr(error_code);

	if (msg)
		cas_printf(LOG_ERR, "%s\n", msg);
}

const char *get_cache_state_name(int cache_state, bool detached)
{
	int i;

	if (detached == true)
		return STANDBY_DETACHED_STATE;

	/* iterate over states in reverse order, so that combined states "running&stopping"
	 * would be described as "stopping" */
	for (i = ocf_cache_state_max - 1; i >= 0; --i) {
		if ((cache_state & (1 << i)) > 0) {
			return cache_states_name[i];
		}
	}
	return NOT_RUNNING_STATE;
}

const char *get_core_state_name(int core_state)
{
	if (core_state < 0 || core_state >= ocf_core_state_max)
		return "Invalid";

	return core_states_name[core_state];
}


/**
  * Save to dest an absolute device file path of src.
  * Return number of characters copied to dest if succeed, negative value if failed.
  */
static int get_abs_path(char* dest, size_t dest_len, const char* src, size_t src_len)
{
	int path_len = -FAILURE;
	char *dir_name, *dev_name;
	char *dev = strndup(src, src_len);	// strdup creates hidden malloc
	if (!dev)				// basename/dirname may modify the source and
		goto dev_err;			// segfault when called with a static string

	char *dir = strndup(src, src_len);
	if (!dir)
		goto dir_err;

	dir_name = realpath(dirname(dir), NULL); // realpath creates hidden malloc
	if (!dir_name)
		goto dir_name_err;

	dev_name = basename(dev);
	if (!dev_name)
		goto dev_name_err;

	path_len = snprintf(dest, dest_len, "%s/%s", dir_name, dev_name);

dev_name_err:
	free(dir_name);
dir_name_err:
	free(dir);
dir_err:
	free(dev);
dev_err:
	return path_len;
}

/**
  * @brief get special device file path (/dev/sdX) for disk.
  */
int get_dev_path(const char* disk, char* buf, size_t num)
{
	char *path;
	int err;

	path = realpath(disk, NULL);
	if (!path)
		return FAILURE;

	err = strncpy_s(buf, num, path, MAX_STR_LEN);

	free(path);
	return err;
}

/* Indicate whether given path should be passed without check */
static bool is_dev_link_whitelisted(const char* path)
{
	regex_t regex;
	int result;
	static const char* const whitelist[] = {
			"/dev/cas[0-9]\\+-[0-9]\\+$",
			"/dev/cas[0-9]\\+-[0-9]\\+p[0-9]\\+$",
			"/dev/ram[0-9]\\+$",
			"/dev/ram[0-9]\\+p[0-9]\\+$",
			"/dev/nullb[0-9]\\+$",
			"/dev/drbd[0-9]\\+$",
			"/dev/drbd[0-9]\\+p[0-9]\\+$",
		};
	static const unsigned count = ARRAY_SIZE(whitelist);
	size_t i;

	for (i = 0; i < count; i++) {
		result = regcomp(&regex, whitelist[i], REG_NOSUB);
		if (result)
			return FAILURE;

		result = regexec(&regex, path, 0, NULL, 0);
		regfree(&regex);
		if (!result) {
			return true;
		}
	}

	return false;
}

/* Call this only AFTER normalizing path */
static int _is_by_id_path(const char* dev_path)
{
	static const char dev_by_id_dir[] = "/dev/disk/by-id";

	return (!strncmp(dev_path, dev_by_id_dir,
			 strnlen_s(dev_by_id_dir, sizeof(dev_by_id_dir))));
}

int set_device_path(char *dest_path, size_t dest_len, const char *src_path, size_t src_len)
{
	char abs_dev_path[MAX_STR_LEN];
	int result;

	/* save given path as absolute path in temporary variable */
	if (get_abs_path(abs_dev_path, sizeof(abs_dev_path), src_path, src_len) < 0) {
		cas_printf(LOG_ERR, "Failed to resolve path.\n");
		return FAILURE;
	}

	/* check if given dev_path is whitelisted and then pass it as path or not */
	if (is_dev_link_whitelisted(abs_dev_path)){
		result = strncpy_s(dest_path, dest_len, abs_dev_path, sizeof(abs_dev_path));
		return result ?: SUCCESS;
	}

	if (_is_by_id_path(abs_dev_path)) {
		result = strncpy_s(dest_path, dest_len, abs_dev_path,
		    strnlen_s(abs_dev_path, sizeof(abs_dev_path)));
		if (!result)
			return SUCCESS;
		else
			cas_printf(LOG_ERR, "Internal error copying device path\n");
	}

	cas_printf(LOG_ERR, "Please use correct by-id path to the device %s.\n",
		   src_path);

	return FAILURE;
}

int get_core_info(int fd, int cache_id, int core_id,
		  struct kcas_core_info *info, bool by_id_path)
{
	memset(info, 0, sizeof(*info));
	info->cache_id = cache_id;
	info->core_id = core_id;

	if (ioctl(fd, KCAS_IOCTL_CORE_INFO, info) < 0) {
		return FAILURE;
	}

	if (!by_id_path) {
		if (get_dev_path(info->core_path_name, info->core_path_name,
				 sizeof(info->core_path_name))) {
			cas_printf(LOG_WARNING, "WARNING: Can not resolve path to core %d "
				   "from cache %d. By-id path will be shown for that core.\n",
				   core_id, cache_id);
		}
	}

	return SUCCESS;
}

static int get_core_device(int cache_id, int core_id, struct core_device *core, bool by_id_path)
{
	int fd;
	struct kcas_core_info cmd_info;

	if (!core)
		return FAILURE;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (get_core_info(fd, cache_id, core_id, &cmd_info, by_id_path)) {
		cas_printf(LOG_ERR, "Error while retrieving stats\n");
		print_err(cmd_info.ext_err_code);
		close(fd);
		return FAILURE;
	}

	close(fd);

	core->id = core_id;
	core->cache_id = cache_id;
	strncpy_s(core->path, sizeof(core->path), cmd_info.core_path_name,
		sizeof(cmd_info.core_path_name));
	memcpy_s(&core->info, sizeof(core->info),
		&cmd_info, sizeof(cmd_info));

	return SUCCESS;
}

int get_cache_count(int fd)
{
	struct kcas_cache_count cmd;

	if (ioctl(fd, KCAS_IOCTL_GET_CACHE_COUNT, &cmd) < 0)
		return 0;

	return cmd.cache_count;
}

int *get_cache_ids(int *caches_count)
{
	int i, fd, status;
	struct kcas_cache_list cache_list;
	int *cache_ids = NULL;
	int count, chunk_size;

	fd = open_ctrl_device();
	if (fd == -1)
		return NULL;

	count = get_cache_count(fd);

	if (count <= 0) {
		goto error_out;
	}

	cache_ids = malloc(count * sizeof(*cache_ids));
	if (cache_ids == NULL) {
		goto error_out;
	}

	memset(&cache_list, 0, sizeof(cache_list));

	*caches_count = 0;

	chunk_size = CACHE_LIST_ID_LIMIT;
	cache_list.id_position = 0;
	cache_list.in_out_num = chunk_size;
	do {
		if ((status = ioctl(fd, KCAS_IOCTL_LIST_CACHE, &cache_list)) < 0) {
			if (errno != EINVAL) {
				cas_printf(LOG_ERR, "Error while retrieving cache properties %d %d\n",
					errno, status);
				free(cache_ids);
				cache_ids = NULL;
				*caches_count = 0;
				break;
			}
		}

		/* iterate through id table and get status */
		for (i = 0; i < cache_list.in_out_num; i++) {
			cache_ids[(*caches_count)] = cache_list.cache_id_tab[i];
			(*caches_count)++;
			if (*caches_count >= count) {
				break;
			}
		}

		cache_list.id_position += chunk_size;
	} while (cache_list.in_out_num >= chunk_size); /* repeat until there is no more devices on the list */

error_out:
	close(fd);
	return cache_ids;
}

/**
 * @brief function returns pointer to cache device given cache_info structure.
 *
 * structure is mallocated, and therefore it is callers responsibility to free it.
 *
 * @return valid pointer to a structure or NULL if error happened
 */
struct cache_device *get_cache_device(const struct kcas_cache_info *info, bool by_id_path)
{
	int core_id, cache_id, ret;
	struct cache_device *cache;
	struct core_device core;
	cache_id = info->cache_id;
	size_t cache_size;

	cache_size = sizeof(*cache);
	cache_size += info->info.core_count * sizeof(cache->cores[0]);

	cache = (struct cache_device *) malloc(cache_size);
	if (NULL == cache) {
		return NULL;
	}

	cache->core_count = 0;
	cache->expected_core_count = info->info.core_count;
	cache->id = cache_id;
	cache->state = info->info.state;
	cache->standby_detached = info->info.standby_detached;

	if (strncpy_s(cache->device, sizeof(cache->device),
			info->cache_path_name,
			sizeof(info->cache_path_name))) {
		free(cache);
		return NULL;
	}

	cache->mode = info->info.cache_mode;
	cache->dirty = info->info.dirty;
	cache->flushed = info->info.flushed;
	cache->cleaning_policy = info->info.cleaning_policy;
	cache->promotion_policy = info->info.promotion_policy;
	cache->size = info->info.cache_line_size;

	if ((info->info.state & (1 << ocf_cache_state_running)) == 0) {
		return cache;
	}

	for (cache->core_count = 0; cache->core_count < info->info.core_count; ++cache->core_count) {
		core_id = info->core_id[cache->core_count];

		ret = get_core_device(cache_id, core_id, &core, by_id_path);
		if (0 != ret) {
			break;
		} else {
			memcpy_s(&cache->cores[cache->core_count],
				sizeof(cache->cores[cache->core_count]),
				&core, sizeof(core));
		}
	}

	return cache;
}

/**
 * @brief function returns pointer to cache device given cache id and fd of /dev/cas_ctrl
 *
 * structure is mallocated, and therefore it is callers responsibility to free it.
 *
 * @param fd valid file descriptor to /dev/cas_ctrl
 * @param cache_id cache id (1...)
 * @return valid pointer to a structure or NULL if error happened
 */
struct cache_device *get_cache_device_by_id_fd(int cache_id, int fd, bool by_id_path)
{
	struct kcas_cache_info cmd_info;

	memset(&cmd_info, 0, sizeof(cmd_info));
	cmd_info.cache_id = cache_id;

	if (ioctl(fd, KCAS_IOCTL_CACHE_INFO, &cmd_info) < 0) {
		if (errno != EINVAL)
			return NULL;
	}

	return get_cache_device(&cmd_info, by_id_path);
}

void free_cache_devices_list(struct cache_device **caches, int caches_count)
{
	int i;
	for (i = 0; i < caches_count; ++i) {
		free(caches[i]);
		caches[i] = NULL;
	}
	free(caches);
}

struct cache_device **get_cache_devices(int *caches_count, bool by_id_path)
{
	int i, fd, status, chunk_size, count;
	struct kcas_cache_list cache_list;
	struct cache_device **caches = NULL;
	struct cache_device *tmp_cache;

	*caches_count = -1;

	fd = open_ctrl_device();
	if (fd == -1)
		return NULL;

	*caches_count = count = get_cache_count(fd);
	if (count <= 0) {
		goto error_out;
	}

	memset(&cache_list, 0, sizeof(cache_list));
	caches = malloc(count * sizeof(*caches));

	if (NULL == caches) {
		*caches_count = -1;
		goto error_out;
	}

	(*caches_count) = 0;

	chunk_size = CACHE_LIST_ID_LIMIT;

	cache_list.id_position = 0;
	cache_list.in_out_num = chunk_size;
	do {
		if ((status = ioctl(fd, KCAS_IOCTL_LIST_CACHE, &cache_list)) < 0) {
			if (errno != EINVAL) {
				cas_printf(LOG_ERR, "Error while retrieving cache properties %d %d\n",
					errno, status);
				free_cache_devices_list(caches, *caches_count);
				*caches_count = -1;
				caches = NULL;
				goto error_out;
			}
		}

		/* iterate through id table and get status */
		for (i = 0; i < cache_list.in_out_num; i++) {
			if ((tmp_cache = get_cache_device_by_id_fd(cache_list.cache_id_tab[i],
								   fd, by_id_path)) == NULL) {
				cas_printf(LOG_ERR, "Failed to retrieve cache information!\n");
				continue;
			}
			caches[(*caches_count)] = tmp_cache;
			(*caches_count)++;
			if (*caches_count >= count) {
				break;
			}
		}
		cache_list.id_position += chunk_size;
	} while (cache_list.in_out_num >= chunk_size); /* repeat until there is no more devices on the list */

error_out:
	close(fd);
	return caches;
}

int caches_compare(const void *a, const void *b)
{
	int a_id = (*(struct cache_device**)a)->id;
	int b_id = (*(struct cache_device**)b)->id;
	return a_id - b_id;
}

int check_cache_already_added(const char *cache_device) {
	struct cache_device **caches, *curr_cache;
	int caches_count, i;

	caches = get_cache_devices(&caches_count, false);

	if (NULL == caches) {
		return SUCCESS;
	}

	for (i = 0; i < caches_count; ++i) {
		curr_cache = caches[i];
		if (0 == strncmp(cache_device, curr_cache->device, MAX_STR_LEN)) {
			free_cache_devices_list(caches, caches_count);
			return FAILURE;
		}
	}

	free_cache_devices_list(caches, caches_count);

	return SUCCESS;
}

static void check_cache_scheduler(const char *cache_device, const char *elv_name)
{
	if (strnlen_s(elv_name, MAX_ELEVATOR_NAME) == 3 &&
	    !strncmp(elv_name, "cfq", 3)) {
		cas_printf(LOG_INFO,
			   "I/O scheduler for cache device %s is %s. This could cause performance drop.\n"
			   "Consider switching I/O scheduler to deadline or noop.\n",
			   cache_device, elv_name);
	}
}

int start_cache(uint16_t cache_id, unsigned int cache_init,
		const char *cache_device, ocf_cache_mode_t cache_mode,
		ocf_cache_line_size_t line_size, int force)
{
	int fd = 0;
	struct kcas_start_cache cmd;
	int status;
	double min_free_ram_gb;

	/* check if cache device given exists */
	fd = open(cache_device, 0);
	if (fd < 0) {
		cas_printf(LOG_ERR, "Device %s not found.\n", cache_device);
		return FAILURE;
	}
	close(fd);

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));

	cmd.cache_id = cache_id;
	cmd.init_cache = cache_init;
	if (set_device_path(cmd.cache_path_name, sizeof(cmd.cache_path_name),
			    cache_device, MAX_STR_LEN) != SUCCESS) {
		close(fd);
		return FAILURE;
	}
	cmd.caching_mode = cache_mode;
	cmd.line_size = line_size;
	cmd.force = (uint8_t)force;

	status = run_ioctl_interruptible_retry(fd, KCAS_IOCTL_START_CACHE, &cmd,
			"Starting cache", cache_id, OCF_CORE_ID_INVALID);
	cache_id = cmd.cache_id;
	if (status < 0) {
		close(fd);

		if (cmd.ext_err_code == OCF_ERR_NO_FREE_RAM) {
			min_free_ram_gb = cmd.min_free_ram;
			min_free_ram_gb /= GiB;

			cas_printf(LOG_ERR, "Not enough free RAM.\n"
					"You need at least %0.2fGB to start cache"
					" with cache line size equal %llukB.\n",
					min_free_ram_gb, line_size / KiB);

			if (64 * KiB > line_size)
				cas_printf(LOG_ERR, "Try with greater cache line size.\n");

			return FAILURE;
		} else {
			cas_printf(LOG_ERR, "Error inserting cache %d\n", cache_id);
			if (FAILURE == check_cache_already_added(cache_device)) {
				cas_printf(LOG_ERR, "Cache device '%s' is already used as cache.\n",
				cache_device);
			} else {
				print_err(cmd.ext_err_code);
			}
			return FAILURE;
		}
	}

	check_cache_scheduler(cache_device, cmd.cache_elevator);

	check_cache_state_incomplete(cache_id, fd);
	close(fd);

	cas_printf(LOG_INFO, "Successfully added cache instance %u\n", cache_id);

	return SUCCESS;
}

int stop_cache(uint16_t cache_id, int flush)
{
	int fd = 0;
	struct kcas_stop_cache cmd;

	/* don't even attempt ioctl if filesystem is mounted */
	if (check_if_mounted(cache_id, CHECK_IF_CACHE_IS_MOUNTED) == FAILURE) {
		return FAILURE;
	}

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.flush_data = flush;

	if(run_ioctl_interruptible_retry(fd, KCAS_IOCTL_STOP_CACHE, &cmd, "Stopping cache",
			cache_id, OCF_CORE_ID_INVALID) < 0) {
		close(fd);
		if (OCF_ERR_FLUSHING_INTERRUPTED == cmd.ext_err_code) {
			cas_printf(LOG_ERR, "You have interrupted stopping of cache. CAS continues\n"
				"to operate normally. If you want to stop cache without fully\n"
				"flushing dirty data, use '-n' option.\n");
			return INTERRUPTED;
		} else if (cmd.ext_err_code == OCF_ERR_WRITE_CACHE){
			cas_printf(LOG_ERR, "Removed cache %d with errors\n", cache_id);
			print_err(cmd.ext_err_code);
			return FAILURE;
		} else {
			cas_printf(LOG_ERR, "Error while removing cache %d\n", cache_id);
			print_err(cmd.ext_err_code);
			return FAILURE;
		}
	}
	close(fd);
	return SUCCESS;
}

/*
 * @brief check caching mode
 * @param[in] ctrl_fd file descriptor of opened control utility
 * @param[in] cache_id id of cache device
 * @param[out] mode mode identifier as integer
 * @return exit code of successful completion is 0; nonzero exit code means failure
 */
int get_cache_mode(int ctrl_fd, unsigned int cache_id, int *mode)
{
	struct kcas_cache_info cmd_info;

	memset(&cmd_info, 0, sizeof(cmd_info));
	cmd_info.cache_id = cache_id;

	if (ioctl(ctrl_fd, KCAS_IOCTL_CACHE_INFO, &cmd_info) < 0)
	{
		if (cmd_info.ext_err_code == OCF_ERR_CACHE_STANDBY)
			print_err(cmd_info.ext_err_code);
		return FAILURE;
	}
	*mode = cmd_info.info.cache_mode;
	return SUCCESS;
}

int set_cache_mode(unsigned int cache_mode, unsigned int cache_id, int flush)
{
	int fd = 0;
	int orig_mode;
	struct kcas_set_cache_state cmd;
	bool flush_param_required;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (get_cache_mode(fd, cache_id, &orig_mode)) {
		cas_printf(LOG_ERR, "Error while retrieving cache properties.\n");
		close(fd);
		return FAILURE;
	}

	/* If flushing mode is undefined, set it to default unless we're transitioning
	 * out of lazy write cache mode (like WB or WO), in which case user must explicitly
	 * state his preference */
	flush_param_required = ocf_mngt_cache_mode_has_lazy_write(orig_mode) &&
			!ocf_mngt_cache_mode_has_lazy_write(cache_mode);
	if (-1 == flush) {
		if (flush_param_required) {
			cas_printf(LOG_ERR, "Error: Required parameter (‘--flush-cache’) was not specified.\n");
			close(fd);
			return FAILURE;
		} else {
			flush=NO;
		}
	}

	if (flush_param_required) {
		if (1 == flush) {
			cas_printf(LOG_INFO, "CAS is currently flushing dirty data to primary storage devices.\n");
		} else {
			cas_printf(LOG_INFO, "CAS is currently migrating from %s to %s mode.\n"
				"Dirty data are being flushed to primary storage device in background.\n"
				"Please find flushing progress via statistics command (‘casadm -P’).\n",
				cache_mode_to_name_long(orig_mode),
				cache_mode_to_name_long(cache_mode));
		}
	}
	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.caching_mode = cache_mode;
	cmd.flush_data = flush;

	if (run_ioctl_interruptible_retry(fd, KCAS_IOCTL_SET_CACHE_STATE, &cmd, "Setting mode",
			cache_id, OCF_CORE_ID_INVALID) < 0) {
		close(fd);
		if (OCF_ERR_FLUSHING_INTERRUPTED == cmd.ext_err_code) {
			assert(flush);
			cas_printf(LOG_ERR,
				"Interrupted flushing of dirty data. Software prevented switching\n"
				"of cache mode. If you want to switch cache mode immediately, use\n"
				"'--flush-cache no' parameter.\n");
			return INTERRUPTED;
		} else if (OCF_ERR_CACHE_STANDBY == cmd.ext_err_code) {
			print_err(cmd.ext_err_code);
			return FAILURE;
		} else {
			cas_printf(LOG_ERR, "Error while setting cache state for cache %d\n",
				cache_id);
			print_err(cmd.ext_err_code);
			return FAILURE;
		}
	}
	close(fd);

	return SUCCESS;
}

static void print_param(FILE *intermediate_file, struct cas_param *param)
{
	if (param->value_names) {
		fprintf(intermediate_file, "%s%s,%s\n", TAG(TABLE_ROW),
			param->name, param->value_names[param->value]);
	} else {
		char *unit = param->unit ?: "";
		fprintf(intermediate_file, "%s%s,%u %s\n", TAG(TABLE_ROW),
			param->name, param->value, unit);
	}
	fflush(intermediate_file);
}

int core_params_set(unsigned int cache_id, unsigned int core_id,
		struct cas_param *params)
{
	int cache_mode = ocf_cache_mode_none;
	struct kcas_set_core_param cmd = {0};
	int fd = 0;
	int i;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (get_cache_mode(fd, cache_id, &cache_mode)) {
		close(fd);
		return FAILURE;
	}

	if (ocf_cache_mode_pt == cache_mode) {
		cas_printf(LOG_WARNING, "Changing parameters for core in Pass-Through mode."
				" New values will be saved but will not be effective"
				" until switching to another cache mode.\n");
	}

	for (i = 0; params[i].name; ++i) {
		if (!params[i].select)
			continue;

		cmd.cache_id = cache_id;
		cmd.core_id = core_id;
		cmd.param_id = i;
		cmd.param_value = params[i].value;

		if (run_ioctl(fd, KCAS_IOCTL_SET_CORE_PARAM, &cmd) < 0) {
			close(fd);
			if (cmd.ext_err_code == OCF_ERR_CACHE_STANDBY) {
				print_err(cmd.ext_err_code);
			}
			return FAILURE;
		}
	}

	close(fd);
	return SUCCESS;
}

int core_params_get(unsigned int cache_id, unsigned int core_id,
		struct cas_param *params, unsigned int output_format)
{
	struct kcas_get_core_param cmd = {0};
	FILE *intermediate_file[2];
	int fd = 0;
	int i;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		close(fd);
		return FAILURE;
	}

	fprintf(intermediate_file[1], TAG(TABLE_HEADER) "Parameter name,Value\n");
	fflush(intermediate_file[1]);

	for (i = 0; params[i].name; ++i) {
		if (!params[i].select)
			continue;

		cmd.cache_id = cache_id;
		cmd.core_id = core_id;
		cmd.param_id = i;

		if (run_ioctl(fd, KCAS_IOCTL_GET_CORE_PARAM, &cmd) < 0) {
			if (cmd.ext_err_code == OCF_ERR_CACHE_NOT_EXIST)
				cas_printf(LOG_ERR, "Cache id %d not running\n", cache_id);
			else if (cmd.ext_err_code == OCF_ERR_CORE_NOT_AVAIL)
				cas_printf(LOG_ERR, "Core id %d not available\n", core_id);
			else {
				print_err(cmd.ext_err_code);
			}
			fclose(intermediate_file[0]);
			fclose(intermediate_file[1]);
			close(fd);
			return FAILURE;
		}

		if (params[i].transform_value)
			params[i].value = params[i].transform_value(cmd.param_value);
		else
			params[i].value = cmd.param_value;

		print_param(intermediate_file[1], &params[i]);
	}

	close(fd);

	fclose(intermediate_file[1]);
	stat_format_output(intermediate_file[0], stdout, output_format);
	fclose(intermediate_file[0]);

	return SUCCESS;
}

int cache_params_set(unsigned int cache_id, struct cas_param *params)
{
	int cache_mode = ocf_cache_mode_none;
	struct kcas_set_cache_param cmd = {0};
	int fd = 0;
	int i;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (get_cache_mode(fd, cache_id, &cache_mode)) {
		close(fd);
		return FAILURE;
	}

	if (ocf_cache_mode_pt == cache_mode) {
		cas_printf(LOG_WARNING, "Changing parameters for core in Pass-Through mode."
				" New values will be saved but will not be effective"
				" until switching to another cache mode.\n");
	}

	for (i = 0; params[i].name; ++i) {
		if (!params[i].select)
			continue;

		cmd.cache_id = cache_id;
		cmd.param_id = i;
		cmd.param_value = params[i].value;

		if (run_ioctl(fd, KCAS_IOCTL_SET_CACHE_PARAM, &cmd) < 0) {
			if (cmd.ext_err_code == OCF_ERR_CACHE_STANDBY)
				print_err(cmd.ext_err_code);
			close(fd);
			return FAILURE;
		}
	}

	close(fd);
	return SUCCESS;
}

int cache_params_get(unsigned int cache_id, struct cas_param *params,
		unsigned int output_format)
{
	struct kcas_get_cache_param cmd = {0};
	FILE *intermediate_file[2];
	int fd = 0;
	int i;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		close(fd);
		return FAILURE;
	}

	fprintf(intermediate_file[1], TAG(TABLE_HEADER) "Parameter name,Value\n");
	fflush(intermediate_file[1]);

	for (i = 0; params[i].name; ++i) {
		if (!params[i].select)
			continue;

		cmd.cache_id = cache_id;
		cmd.param_id = i;

		if (run_ioctl(fd, KCAS_IOCTL_GET_CACHE_PARAM, &cmd) < 0) {
			if (cmd.ext_err_code == OCF_ERR_CACHE_NOT_EXIST)
				cas_printf(LOG_ERR, "Cache id %d not running\n", cache_id);
			else if (cmd.ext_err_code == OCF_ERR_CACHE_STANDBY)
				print_err(cmd.ext_err_code);
			else
				cas_printf(LOG_ERR, "Can't get parameters\n");
			fclose(intermediate_file[0]);
			fclose(intermediate_file[1]);
			close(fd);
			return FAILURE;
		}

		if (params[i].transform_value)
			params[i].value = params[i].transform_value(cmd.param_value);
		else
			params[i].value = cmd.param_value;

		print_param(intermediate_file[1], &params[i]);
	}

	close(fd);

	fclose(intermediate_file[1]);
	stat_format_output(intermediate_file[0], stdout, output_format);
	fclose(intermediate_file[0]);

	return SUCCESS;
}

int check_core_already_cached(const char *core_device) {
	struct cache_device **caches, *curr_cache;
	struct core_device *curr_core;
	int caches_count, i, j;
	char core_device_path[MAX_STR_LEN];

	if (get_dev_path(core_device, core_device_path, sizeof(core_device_path)))
		return SUCCESS;

	caches = get_cache_devices(&caches_count, false);

	if (NULL == caches) {
		return SUCCESS;
	}

	for (i = 0; i < caches_count; ++i) {
		curr_cache = caches[i];
		for (j = 0; j < curr_cache->core_count; ++j) {
			curr_core = &curr_cache->cores[j];
			if (curr_core->info.state == ocf_core_state_active && 0 ==
			strncmp(core_device_path, curr_core->path, MAX_STR_LEN)) {
				free_cache_devices_list(caches, caches_count);
				return FAILURE;
			}
		}
	}

	free_cache_devices_list(caches, caches_count);

	return SUCCESS;
}

/**
 * @brief convert string to int
 *
 * @param[in] start string beginning
 * @param[out] end optional pointer to character past the end of integer
 * @param[out] val integer value
 * @return true in case of success, false in case of failure
 */
bool str_to_int(const char* start, char** end, int *val)
{
	long int _val;
	char *_end = (char *)start;

	_val = strtol(start, &_end, 10);

	if (_end == start) {
		/* no integer found */
		return false;
	}

	if (_val < INT_MIN || _val > INT_MAX) {
		/* value out of int range */
		return false;
	}

	/* 0 might indicate strtol error, so try to check if the
	   input is really 0. This might not be  bullet-proof, but enough
	   for us. */
	if (_val == 0 && *(_end - 1) != '0') {
		/* doesn't look like 0, more likely a parsing error */
		return false;
	}

	*val = (int)_val;
	if (end)
		*end = _end;

	return true;
}


static bool get_core_cache_id_from_string(char *str,
	int *cache_id, int *core_id)
{
	char *end;

	if (!str_to_int(str, &end, cache_id))
		return false;

	if (*end != '-') {
		/* invalid separator */
		return false;
	}

	if (!str_to_int(end + 1, NULL, core_id))
		return false;

	return true;
}

int get_inactive_core_count(const struct kcas_cache_info *cache_info)
{
	struct cache_device *cache;
	int inactive_cores = 0;
	int i;

	cache = get_cache_device(cache_info, false);
	if (!cache)
		return -1;

	for (i = 0; i < cache->core_count; i++) {
		if (cache->cores[i].info.state == ocf_core_state_inactive)
			inactive_cores++;
	}

	free(cache);

	return inactive_cores;
}


/**
 * @brief check for illegal recursive core configuration
 *
 * Function returns 1 (FAILURE/true) if it detects that adding core_device to
 *   cache_id will  result in illegal multilevel configuration.
 * Function returns 0 (SUCCESS/false) if it detects that it is fine to add
 *   core_device to cache_id  and it will NOT result in illegal multilevel
 *   configuration.
 *
 * Here is example of such illegal configuration:
 *
 * type      id   disk             device
 * cache     1    /dev/sdc1        -
 * +core     1    /dev/sdd1        /dev/cas1-1
 * +core     2    /dev/cas1-1	   /dev/cas1-2
 *
 * Here is another example of illegal configuration (notice that it is indirect, and hence
 * whole multilevel caching hierarchy has to be parsed)
 *
 * type      id   disk              device
 * cache     1    /dev/sdc1         -
 * +core     1    /dev/sdd1         /dev/cas1-1
 * +core     2    /dev/cas2-1	    /dev/cas1-2
 * cache     2    /dev/sdc2         -
 * +core     1    /dev/cas1-1	    /dev/cas2-1
 *
 * (in above example adding core 2 to cache shouldn't be allowed as this is effectively adding same
 * disk device (/dev/sdd1) to the same cache (/dev/sdc1) twice).
 *
 * @param cache_id cache to which new core is being added
 * @param core_device path to a core device that is being added
 * @param fd valid file descriptor for /dev/cas_ctrl device
 * @return 0 if check is successful and on illegal recursion is detected.
 *		1 if illegal config detected.
 */
int illegal_recursive_core(unsigned int cache_id, const char *core_device, int core_path_size, int fd)
{
	char tmp_path[MAX_STR_LEN];
	char core_path[MAX_STR_LEN];	/* extracted actual path */
	int dev_core_id, dev_cache_id;  /* cache_id and core_id for currently
					 * analyzed device */
	struct stat st_buf;
	int i;
	static const char cas_pattern[] = "/dev/cas";
	struct cache_device *cache; /*structure containing data on cache device*/

	while (true) {
		/*
		 * if core_device is an cas device (or a symlink to
		 * cas device) check if its cache device is cache id. if
		 * it is, return an error, as this will lead to illegal
		 * multilevel configuration.
		 */
		if (lstat(core_device, &st_buf)) {
			cas_printf(LOG_ERR, "ERROR: lstat failed for %s.\n",
				   core_device);
			return FAILURE;
		}

		if (get_dev_path(core_device, core_path, sizeof(core_path)))
			return FAILURE;

		/* if core_path does NOT begin with /dev/cas, report success
		 * as it certainly is not case of */
		if (strncmp(cas_pattern, core_path, sizeof(cas_pattern) - 1)) {
			return SUCCESS;
		}

		if (!get_core_cache_id_from_string(
				core_path + sizeof(cas_pattern) - 1,
				&dev_cache_id,
				&dev_core_id)) {
			cas_printf(LOG_ERR, "Failed to extract core/cache "
				   "id from %s path\n", core_path);
			return FAILURE;
		}

		if (dev_cache_id == cache_id) {
			cas_printf(LOG_ERR, "Core device '%s' is already cached"
				   " on cache device %d. - "
				   "illegal multilevel caching configuration.\n",
				   core_device, cache_id);
			return FAILURE;
		}
		/* possibly legal multilevel caching configuration - do one more
		 * iteration of this loop*/

		/* get underlying core device of dev_cache_id-dev_core_id */
		cache = get_cache_device_by_id_fd(dev_cache_id, fd, false);

		if (!cache) {
			cas_printf(LOG_ERR, "Failed to extract statistics for "
				   "cache device %d\n", dev_cache_id);
			return FAILURE;
		}

		/* lookup for record for appropriate core */
		for (i = 0; i != cache->core_count ; ++i) {
			if (cache->cores[i].id == dev_core_id) {
				strncpy_s(tmp_path, sizeof(tmp_path),
					  cache->cores[i].path,
					  strnlen_s(cache->cores[i].path,
						    sizeof(cache->cores[i].path)));
				core_device = tmp_path;
				break;
			}
		}

		/* make sure that loop above resulted in correct assignment */
		if (i == cache->core_count) {
			cas_printf(LOG_ERR, "Failed to extract statistics for "
				   "core device %d-%d. Does it exist?\n",
				   dev_cache_id, dev_core_id);
			free(cache);
			return FAILURE;
		}

		free(cache);
	}
}

int add_core(unsigned int cache_id, unsigned int core_id, const char *core_device,
		int try_add, int update_path)
{
	int fd = 0, user_core_path_size;
	struct kcas_insert_core cmd;
	struct stat query_core;
	const char *core_path;      /* core path sent down to kernel  */
	const char *user_core_path; /* core path provided by user */

	if (try_add && core_id == OCF_CORE_ID_INVALID) {
		cas_printf(LOG_ERR, "Option '--core-id' is missing\n");
		return FAILURE;
	}

	/* Check if core device provided is valid */
	fd = open(core_device, 0);
	if (fd < 0) {
		cas_printf(LOG_ERR, "Device %s not found.\n", core_device);
		return FAILURE;
	}
	close(fd);

	/* Check if the core device is a block device or a file */
	if (stat(core_device, &query_core)) {
		cas_printf(LOG_ERR, "Could not stat target core device %s!\n", core_device);
		return FAILURE;
	}

	if (!S_ISBLK(query_core.st_mode)) {
		cas_printf(LOG_ERR, "Core object %s is not supported!\n", core_device);
		return FAILURE;
	}

	memset(&cmd, 0, sizeof(cmd));
	if (set_device_path(cmd.core_path_name, sizeof(cmd.core_path_name),
			    core_device, MAX_STR_LEN) != SUCCESS)
		return FAILURE;

	user_core_path = core_device;
	user_core_path_size = strnlen_s(core_device, MAX_STR_LEN);
	core_path = cmd.core_path_name;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	/* check for illegal recursive caching config. */
	if (illegal_recursive_core(cache_id, user_core_path,
		user_core_path_size, fd)) {
		close(fd);
		return FAILURE;
	}

	cmd.cache_id = cache_id;
	cmd.core_id = core_id;
	cmd.try_add = try_add;
	cmd.update_path = update_path;

	if (ioctl(fd, KCAS_IOCTL_INSERT_CORE, &cmd) < 0) {
		close(fd);
		cas_printf(LOG_ERR, "Error while adding core device to cache instance %d\n",
			cache_id);
		if (OCF_ERR_NOT_OPEN_EXC == cmd.ext_err_code) {
			if (FAILURE == check_core_already_cached(core_path)) {
				cas_printf(LOG_ERR, "Core device '%s' is already cached.\n",
					user_core_path);
			} else {
				cas_printf(LOG_ERR, "Failed to open '%s' device"
				  " exclusively. Please close all applications "
				  "accessing it or unmount the device.\n",
				  user_core_path);
			}
		} else {
			print_err(cmd.ext_err_code);
		}
		return FAILURE;
	}
	close(fd);

	if (try_add) {
		cas_printf(LOG_INFO, "Successfully added device in try add mode %s\n", user_core_path);
	} else {
		core_id = cmd.core_id;

		cas_printf(LOG_INFO, "Successfully added core %u to cache instance %u\n", core_id, cache_id);
	}

	return SUCCESS;
}

int check_if_mounted(int cache_id, int core_id)
{
	FILE *mtab;
	struct mntent *mstruct;
	char dev_buf[80];
	int difference = 0, error = 0;
	if (core_id >= 0) {
		/* verify if specific core is mounted */
		snprintf(dev_buf, sizeof(dev_buf), "/dev/cas%d-%d", cache_id, core_id);
	} else {
		/* verify if any core from given cache is mounted */
		snprintf(dev_buf, sizeof(dev_buf), "/dev/cas%d-", cache_id);
	}

	mtab = setmntent("/etc/mtab", "r");
	if (!mtab)
	{
		cas_printf(LOG_ERR, "Error while accessing /etc/mtab\n");
		return FAILURE;
	}

	while ((mstruct = getmntent(mtab)) != NULL) {
		error = strcmp_s(mstruct->mnt_fsname, PATH_MAX, dev_buf, &difference);
		/* mstruct->mnt_fsname is /dev/... block device path, not a mountpoint */
		if (error != EOK)
			return FAILURE;
		if (!difference) {
			if (core_id<0) {
				cas_printf(LOG_ERR,
					   "Can't stop cache instance %d. Device %s is mounted!\n",
					   cache_id, mstruct->mnt_fsname);
			} else {
				cas_printf(LOG_ERR,
					   "Can't remove core %d from cache %d."
					   " Device %s is mounted!\n",
					   core_id, cache_id, mstruct->mnt_fsname);
			}
			return FAILURE;
		}
	}
	return SUCCESS;

}

int remove_core(unsigned int cache_id, unsigned int core_id,
		bool detach, bool force_no_flush)
{
	int fd = 0;
	struct kcas_remove_core cmd;

	/* don't even attempt ioctl if filesystem is mounted */
	if (SUCCESS != check_if_mounted(cache_id, core_id)) {
		return FAILURE;
	}

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.core_id = core_id;
	cmd.force_no_flush = force_no_flush;
	cmd.detach = detach;

	if (run_ioctl_interruptible(fd, KCAS_IOCTL_REMOVE_CORE, &cmd,
			cmd.detach?"Detaching core":"Removing core", cache_id, core_id) < 0) {
		close(fd);
		if (cmd.ext_err_code == OCF_ERR_FLUSHING_INTERRUPTED) {
			cas_printf(LOG_ERR, "You have interrupted %s of core. "
					"CAS continues to operate normally.\n",
					detach ? "detaching" : "removal");
			return INTERRUPTED;
		} else if (cmd.ext_err_code == OCF_ERR_CORE_IN_INACTIVE_STATE) {
			cas_printf(LOG_ERR, "Core is inactive. To manage the "
					"inactive core use '--remove-inactive' "
					"command.\n");
			return FAILURE;
		} else if (cmd.ext_err_code == KCAS_ERR_DETACHED) {
			print_err(cmd.ext_err_code);
			return FAILURE;
		} else {
			cas_printf(LOG_ERR, "Error while %s core device %d "
					"from cache instance %d\n",
					detach ? "detaching" : "removing",
					core_id, cache_id);
			print_err(cmd.ext_err_code);
			return FAILURE;
		}
	}
	close(fd);

	return SUCCESS;
}

void check_cache_state_incomplete(int cache_id, int fd) {
	struct cache_device *cache =
		get_cache_device_by_id_fd(cache_id, fd, false);

	if (cache == NULL)
		return;

	if (cache->state & (1 << ocf_cache_state_incomplete)) {
		cas_printf(LOG_WARNING, "WARNING: Cache is in incomplete state - "
				"at least one core is inactive\n");
	}

	free(cache);
}

int remove_inactive_core(unsigned int cache_id, unsigned int core_id,
		bool force)
{
	int fd = 0;
	struct kcas_remove_inactive cmd;

	/* don't even attempt ioctl if filesystem is mounted */
	if (SUCCESS != check_if_mounted(cache_id, core_id)) {
		return FAILURE;
	}

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.core_id = core_id;
	cmd.force = force;

	if (run_ioctl(fd, KCAS_IOCTL_REMOVE_INACTIVE, &cmd) < 0) {
		close(fd);
		if (cmd.ext_err_code == KCAS_ERR_CORE_IN_ACTIVE_STATE) {
			cas_printf(LOG_ERR, "Core is active. "
					"To manage the active core use "
					"'--remove-core' command.\n");
		} else {
			cas_printf(LOG_ERR, "Error while removing inactive "
					"core device %d from cache instance "
					"%d\n", core_id, cache_id);
			print_err(cmd.ext_err_code);
		}
		return FAILURE;
	}
	close(fd);

	return SUCCESS;
}

int core_pool_remove(const char *core_device)
{
	struct kcas_core_pool_remove cmd;
	int fd;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	if (set_device_path(cmd.core_path_name, sizeof(cmd.core_path_name),
			    core_device, MAX_STR_LEN) != SUCCESS) {
		close(fd);
		return FAILURE;
	}

	if (ioctl(fd, KCAS_IOCTL_CORE_POOL_REMOVE, &cmd) < 0) {
		cas_printf(LOG_ERR, "Error while removing device %s from core pool\n",
				core_device);
		print_err(cmd.ext_err_code);
		close(fd);
		return FAILURE;
	}

	close(fd);
	return SUCCESS;
}

int purge_cache(unsigned int cache_id)
{
	int fd = 0;
	struct kcas_flush_cache cmd;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	/* synchronous flag */
	if (run_ioctl_interruptible(fd, KCAS_IOCTL_PURGE_CACHE, &cmd, "Purging cache",
			cache_id, OCF_CORE_ID_INVALID) < 0) {
		close(fd);
		print_err(cmd.ext_err_code);
		return FAILURE;
	}

	close(fd);
	return SUCCESS;
}

#define DIRTY_FLUSHING_WARNING "You have interrupted flushing of cache dirty data. CAS continues to operate\nnormally and dirty data that remains on cache device will be flushed by cleaning thread.\n"
int flush_cache(unsigned int cache_id)
{
	int fd = 0;
	struct kcas_flush_cache cmd;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	/* synchronous flag */
	if (run_ioctl_interruptible_retry(fd, KCAS_IOCTL_FLUSH_CACHE, &cmd, "Flushing cache",
			cache_id, OCF_CORE_ID_INVALID) < 0) {
		close(fd);
		if (OCF_ERR_FLUSHING_INTERRUPTED == cmd.ext_err_code) {
			cas_printf(LOG_ERR, DIRTY_FLUSHING_WARNING);
			return INTERRUPTED;
		} else {
			print_err(cmd.ext_err_code);
			return FAILURE;
		}
	}

	close(fd);
	return SUCCESS;
}

int purge_core(unsigned int cache_id, unsigned int core_id)
{
	int fd = 0;
	struct kcas_flush_core cmd;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.core_id = core_id;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	/* synchronous flag */
	if (run_ioctl_interruptible(fd, KCAS_IOCTL_PURGE_CORE, &cmd, "Purging core", cache_id, core_id) < 0) {
		close(fd);

		print_err(cmd.ext_err_code);

		return FAILURE;
	}

	close(fd);
	return SUCCESS;
}

int flush_core(unsigned int cache_id, unsigned int core_id)
{
	int fd = 0;
	struct kcas_flush_core cmd;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.core_id = core_id;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	/* synchronous flag */
	if (run_ioctl_interruptible_retry(fd, KCAS_IOCTL_FLUSH_CORE, &cmd, "Flushing core", cache_id, core_id) < 0) {
		close(fd);
		if (OCF_ERR_FLUSHING_INTERRUPTED == cmd.ext_err_code) {
			cas_printf(LOG_ERR, DIRTY_FLUSHING_WARNING);
			return INTERRUPTED;
		} else {
			print_err(cmd.ext_err_code);
			return FAILURE;
		}
	}
	close(fd);
	return SUCCESS;
}

struct partition_config_col {
	const char *name;
	int pos;
};

static struct partition_config_col partition_config_columns[] = {
	{ .name = "IO class id", .pos = -1 },
	{ .name = "IO class name", .pos = -1 },
	{ .name = "Eviction priority", .pos = -1 },
	{ .name = "Allocation", .pos = -1 },
	{ .name = NULL }
};

void partition_list_line(FILE *out, struct kcas_io_class *cls, bool csv)
{
	char buffer[128];
	const char *prio;
	char allocation_str[MAX_STR_LEN];

	snprintf(allocation_str, sizeof(allocation_str), "%d.%02d",
					cls->info.max_size/100, cls->info.max_size%100);

	if (OCF_IO_CLASS_PRIO_PINNED == cls->info.priority) {
		prio = csv ? "" : "Pinned";
	} else {
		snprintf(buffer, sizeof(buffer), "%d", cls->info.priority);
		prio = buffer;
	}

	fprintf(out, TAG(TABLE_ROW)"%u,%s,%s,%s\n",
		cls->class_id, cls->info.name, prio, allocation_str);

}

int partition_list(unsigned int cache_id, unsigned int output_format)
{
	struct kcas_io_class io_class = { .ext_err_code = 0 };
	int fd, i = 0, result = 0;
	/* 1 is writing end, 0 is reading end of a pipe */
	FILE *intermediate_file[2];
	bool use_csv, first_col;

	fd = open_ctrl_device();
	if (fd == -1 )
		return FAILURE;


	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		close(fd);
		return FAILURE;
	}

	use_csv = (output_format == OUTPUT_FORMAT_CSV);

	first_col = true;
	fprintf(intermediate_file[1], TAG(TABLE_HEADER));
	for (i = 0; partition_config_columns[i].name; i++) {
		if (!first_col) {
			fputc(',', intermediate_file[1]);
		}
		fprintf(intermediate_file[1], "%s",
			partition_config_columns[i].name);
		first_col = false;
	}
	fputc('\n', intermediate_file[1]);

	for (i = 0; i < OCF_USER_IO_CLASS_MAX; i++, io_class.ext_err_code = 0) {
		io_class.cache_id = cache_id;
		io_class.class_id = i;

		result = run_ioctl(fd, KCAS_IOCTL_PARTITION_INFO, &io_class);
		if (result) {
			if (OCF_ERR_IO_CLASS_NOT_EXIST == io_class.ext_err_code) {
				result = SUCCESS;
				continue;
			} else {
				result = FAILURE;
				break;
			}
		}

		partition_list_line(intermediate_file[1],
			&io_class, use_csv);

	}

	if (io_class.ext_err_code) {
		print_err(io_class.ext_err_code);
	}

	fclose(intermediate_file[1]);
	if (!result && stat_format_output(intermediate_file[0], stdout,
					  use_csv?RAW_CSV:TEXT)) {
		cas_printf(LOG_ERR, "An error occured during statistics formatting.\n");
		result = FAILURE;
	}
	fclose(intermediate_file[0]);
	close(fd);

	return result;
}

enum {
	part_csv_coll_id = 0,
	part_csv_coll_name,
	part_csv_coll_prio,
	part_csv_coll_alloc,
	part_csv_coll_max
};

int partition_is_name_valid(const char *name)
{
	int i;
	int length = strnlen(name, OCF_IO_CLASS_NAME_MAX);
	if (0 == length || length >= OCF_IO_CLASS_NAME_MAX) {
		cas_printf(LOG_ERR, "Empty or too long IO class name\n");
		return FAILURE;
	}

	for (i = 0; i < length; i++) {
		if (name[i] == ',' || name[i] == '"' ||
		    name[i] < 32 || name[i] > 126) {
			cas_printf(LOG_ERR, "Only characters allowed in IO "
				   "class name are low ascii characters, "
				   "excluding control characters, comma and "
				   "quotation mark.\n");
			return FAILURE;
		}
	}

	return SUCCESS;
}

static inline const char *partition_get_csv_col(CSVFILE *csv, int col,
						int *error_col)
{
	const char *val;

	val = csv_get_col(csv, partition_config_columns[col].pos);
	if (!val) {
		*error_col = col;
	}
	return val;
}

static int calculate_max_allocation(uint16_t cache_id, const char *allocation,
		uint32_t *part_size)
{
	float alloc = 0;
	char *end;

	if (strnlen(allocation, MAX_STR_LEN) > 4)
			return FAILURE;

	alloc = strtof(allocation, &end);
	if (alloc > 1 || alloc < 0)
		return FAILURE;

	if (allocation + strnlen(allocation, MAX_STR_LEN) != end)
		return FAILURE;

	*part_size = (uint32_t)round(alloc * 100);

	return SUCCESS;
}


static inline int partition_get_line(CSVFILE *csv,
				     struct kcas_io_classes *cnfg,
				     int *error_col)
{
	uint32_t part_id;
	uint32_t value;
	const char *id, *name, *prio, *alloc;

	id = partition_get_csv_col(csv, part_csv_coll_id, error_col);
	if (!id) {
		return FAILURE;
	}
	name = partition_get_csv_col(csv, part_csv_coll_name, error_col);
	if (!name) {
		return FAILURE;
	}
	prio = partition_get_csv_col(csv, part_csv_coll_prio, error_col);
	if (!prio) {
		return FAILURE;
	}
	alloc = partition_get_csv_col(csv, part_csv_coll_alloc, error_col);
	if (!alloc) {
		return FAILURE;
	}

	/* Validate ID */
	*error_col = part_csv_coll_id;
	if (strempty(id)) {
		return FAILURE;
	}
	if (validate_str_num(id, "id", 0, OCF_IO_CLASS_ID_MAX)) {
		return FAILURE;
	}
	part_id = strtoul(id, NULL, 10);
	if (part_id > OCF_IO_CLASS_ID_MAX) {
		cas_printf(LOG_ERR, "Invalid partition id\n");
		return FAILURE;
	}
	if (!strempty(cnfg->info[part_id].name)) {
		cas_printf(LOG_ERR, "Double configuration for IO class id %u\n",
				part_id);
		return FAILURE;
	}

	/* Validate name */
	*error_col = part_csv_coll_name;
	if (SUCCESS != partition_is_name_valid(name)) {
		return FAILURE;
	}
	strncpy_s(cnfg->info[part_id].name, sizeof(cnfg->info[part_id].name),
		  name, strnlen_s(name, sizeof(cnfg->info[part_id].name)));

	/* Validate Priority*/
	*error_col = part_csv_coll_prio;
	if (strempty(prio)) {
		value = OCF_IO_CLASS_PRIO_PINNED;
	} else {
		if (validate_str_num(prio, "prio", OCF_IO_CLASS_PRIO_HIGHEST,
				OCF_IO_CLASS_PRIO_LOWEST)) {
			return FAILURE;
		}
		value = strtoul(prio, NULL, 10);
	}
	cnfg->info[part_id].priority = value;

	/* Validate Allocation */
	*error_col = part_csv_coll_alloc;
	if (strempty(alloc)) {
		return FAILURE;
	}

	if (calculate_max_allocation(cnfg->cache_id, alloc, &value) == FAILURE)
		return FAILURE;

	cnfg->info[part_id].cache_mode = ocf_cache_mode_max;
	cnfg->info[part_id].min_size = 0;
	cnfg->info[part_id].max_size = value;

	return 0;
}

static int partition_parse_header(CSVFILE *csv)
{
	int i, j, csv_cols;
	const char *col_name;

	csv_cols = csv_count_cols(csv);
	for (i = 0; i < csv_cols; i++) {
		col_name = csv_get_col(csv, i);

		if (!col_name) {
			cas_printf(LOG_ERR, "Cannot parse configuration file.\n");
			return FAILURE;
		}

		for (j = 0; partition_config_columns[j].name; j++) {
			if (!strncmp(col_name, partition_config_columns[j].name, MAX_STR_LEN)) {
				partition_config_columns[j].pos = i;
				break;
			}
		}
		if (!partition_config_columns[j].name) {
			cas_printf(LOG_ERR,
				   "Cannot parse configuration file - unknown column \"%s\".\n",
				   col_name);
			return FAILURE;
		}
	}

	for (i = 0; partition_config_columns[i].name; i++) {
		if (partition_config_columns[i].pos < 0) {
			cas_printf(LOG_ERR,
				   "Cannot parse configuration file - missing column \"%s\".\n",
				   partition_config_columns[i].name);
			return FAILURE;
		}
	}
	return SUCCESS;
}

int partition_get_config(CSVFILE *csv, struct kcas_io_classes *cnfg,
		int cache_id)
{
	int result = 0, count = 0;
	int line = 1;
	int error_col = -1;

	cnfg->cache_id = cache_id;

	/* before reading io class configuration check header */
	if (csv_read(csv)) {
		if (csv_feof(csv)) {
			cas_printf(LOG_ERR,
				   "Empty IO Classes configuration file"
				   " supplied.\n");
			return FAILURE;
		} else {
			cas_printf(LOG_ERR,
				   "I/O error occured while reading"
				   " IO Classes configuration file"
				   " supplied.\n");
			return FAILURE;
		}
	}

	if (partition_parse_header(csv)) {
		cas_printf(LOG_ERR, "Failed to parse I/O classes"
			   " configuration file header. It is either"
			   " malformed or missing.\n"
			   "Please consult Admin Guide to check how"
			   " columns in configuration file should"
			   " be named.\n");
		return FAILURE;
	}

	/* check all lines of input */
	while (!csv_feof(csv)) {
		line++;
		if (csv_read(csv)) {
			if (csv_feof(csv)) {
				break;
			} else {
				result = FAILURE;
				break;
			}
		}

		if (part_csv_coll_max != csv_count_cols(csv)) {
			if (csv_empty_line(csv)) {
				continue;
			} else {
				result = FAILURE;
				break;
			}
		}

		if (partition_get_line(csv, cnfg, &error_col)) {
			result = FAILURE;
			break;
		}

		count++;
	}

	if (result) {
		if (error_col >= 0) {
			cas_printf(LOG_ERR,
				   "Cannot parse configuration file - error in line %d in column %d (%s).\n",
				   line,
				   partition_config_columns[error_col].pos+1,
				   partition_config_columns[error_col].name);
		} else {
			cas_printf(LOG_ERR, "Cannot parse configuration file - error in line %d.\n", line);
		}
	} else if (0 == count) {
		result = FAILURE;
		cas_printf(LOG_ERR, "Empty configuration file\n");
	}

	return result;
}

int partition_set_config(struct kcas_io_classes *cnfg)
{
	int fd;
	int result = 0;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	result = run_ioctl(fd, KCAS_IOCTL_PARTITION_SET, cnfg);
	if (result) {
		if (OCF_ERR_IO_CLASS_NOT_EXIST == cnfg->ext_err_code) {
			result = SUCCESS;
		} else if (OCF_ERR_CACHE_STANDBY == cnfg->ext_err_code) {
			print_err(cnfg->ext_err_code);
			result = FAILURE;
		} else {
			print_err(cnfg->ext_err_code);
			result = FAILURE;
		}
	}

	close(fd);
	return result;
}

int partition_setup(unsigned int cache_id, const char *file)
{
	int result = 0;
	CSVFILE *in;
	struct kcas_io_classes *cnfg = calloc(1, KCAS_IO_CLASSES_SIZE);

	if (!cnfg)
		return FAILURE;

	if (strempty(file)) {
		cas_printf(LOG_ERR, "Invalid path of configuration file\n");
		result = FAILURE;
		goto exit;
	}

	if ('-'==file[0] && (!file[1])) {
		/* configuration is supposed to be read from stdin. Setup
		 * a csv parser treating standard input as input file instead
		 * of opening a regular file */
		in = csv_fopen(stdin);
	} else {
		/* read ioclass configuration from a regular file */
		in = csv_open(file, "r");
	}
	if (NULL == in) {
		cas_printf(LOG_ERR, "Cannot open configuration file %s\n",
				file);
		result = FAILURE;
		goto exit;
	}

	if (0 == partition_get_config(in, cnfg, cache_id)) {
		result = partition_set_config(cnfg);
	} else {
		result = FAILURE;
	}

	if ('-' == file[0] && (!file[1])) {
		/* free assets allocated by CSV parser without actually
		 * closing a file */
		csv_close_nu(in);
	} else {
		csv_close(in);
	}

exit:
	free(cnfg);
	return result;
}

int reset_counters(unsigned int cache_id, unsigned int core_id)
{
	struct kcas_reset_stats cmd;
	int fd = 0;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd, 0, sizeof(cmd));
	cmd.cache_id = cache_id;
	cmd.core_id = core_id;

	if (ioctl(fd, KCAS_IOCTL_RESET_STATS, &cmd) < 0) {
		
		if (OCF_ERR_CACHE_STANDBY == cmd.ext_err_code) {
			print_err(cmd.ext_err_code);
		} else {
			cas_printf(LOG_ERR, "Error encountered while resetting counters\n");
			print_err(cmd.ext_err_code);
		}

		close(fd);
		return FAILURE;
	}

	close(fd);
	return SUCCESS;
}

int cas_module_version(char *buff, int size)
{
	FILE *fd;
	int n_read;

	if (size <= 0 || size > MAX_STR_LEN) {
		return FAILURE;
	}
	memset(buff, 0, size);

	fd = fopen("/sys/module/cas_cache/version", "r");
	if (!fd) {
		return FAILURE;
	}

	n_read = fread(buff, 1, size, fd);
	if (ferror(fd)) {
		n_read = 0;
	}
	fclose(fd);

	if (n_read > 0) {
		buff[n_read - 1] = '\0';
		return SUCCESS;
	} else {
		return FAILURE;
	}
}

int disk_module_version(char *buff, int size)
{
	FILE *fd;
	int n_read;

	if (size <= 0 || size > MAX_STR_LEN) {
		return FAILURE;
	}

	fd = fopen("/sys/module/cas_disk/version", "r");
	if (!fd) {
		return FAILURE;
	}

	n_read = fread(buff, 1, size, fd);
	if (ferror(fd)) {
		n_read = 0;
	}
	fclose(fd);

	if (n_read > 0) {
		buff[n_read - 1] = '\0';
		return SUCCESS;
	} else {
		return FAILURE;
	}
}

float calculate_flush_progress(unsigned dirty, unsigned flushed)
{
	unsigned total_dirty;

	if (!flushed)
		return 0;

	total_dirty = dirty + flushed;
	return total_dirty ? 100. * flushed / total_dirty : 100;
}

int get_flush_progress(int unsigned cache_id, float *progress)
{
	struct kcas_cache_info cmd_info;
	int fd = 0;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	memset(&cmd_info, 0, sizeof(cmd_info));

	cmd_info.cache_id = cache_id;
	if (ioctl(fd, KCAS_IOCTL_CACHE_INFO, &cmd_info) < 0) {
		close(fd);
		return FAILURE;
	}

	*progress = calculate_flush_progress(cmd_info.info.dirty,
			cmd_info.info.flushed);

	close(fd);
	return SUCCESS;
}

struct list_printout_ctx
{
	FILE *intermediate;
	FILE *out;
	int type;
	int result;
};

void *list_printout(void *ctx)
{
	struct list_printout_ctx *spc = ctx;
	if (stat_format_output(spc->intermediate,
			       spc->out, spc->type)) {
		cas_printf(LOG_ERR, "An error occured during statistics formatting.\n");
		spc->result = FAILURE;
	} else {
		spc->result = SUCCESS;
	}

	return NULL;
}

int get_core_pool_count(int fd)
{
	struct kcas_core_pool_count cmd;

	if (ioctl(fd, KCAS_IOCTL_GET_CORE_POOL_COUNT, &cmd) < 0)
		return 0;

	return cmd.core_pool_count;
}

int get_core_pool_devices(struct kcas_core_pool_path *cmd)
{
	int fd, status, result = SUCCESS;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	cmd->core_pool_count = get_core_pool_count(fd);
	if (cmd->core_pool_count <= 0) {
		goto error_out;
	}

	cmd->core_path_tab = malloc(cmd->core_pool_count * MAX_STR_LEN);
	if (NULL == cmd->core_path_tab) {
		cmd->core_pool_count = 0;
		goto error_out;
	}

	if ((status = ioctl(fd, KCAS_IOCTL_GET_CORE_POOL_PATHS, cmd)) < 0) {
		cas_printf(LOG_ERR, "Error while retrieving core pool list %d %d\n",
				errno, status);
		free(cmd->core_path_tab);
		result = FAILURE;
		goto error_out;
	}

error_out:
	close(fd);
	return result;
}

int list_caches(unsigned int list_format, bool by_id_path)
{
	struct cache_device **caches, *curr_cache;
	struct kcas_core_pool_path core_pool_path_cmd = {0};
	struct core_device *curr_core;
	int caches_count, i, j;
	/* 1 is writing end, 0 is reading end of a pipe */
	FILE *intermediate_file[2];
	int result = SUCCESS;
	pthread_t thread;
	struct list_printout_ctx printout_ctx;

	caches = get_cache_devices(&caches_count, by_id_path);
	if (caches_count < 0) {
		cas_printf(LOG_INFO, "Error getting caches list\n");
		return FAILURE;
	}

	if (get_core_pool_devices(&core_pool_path_cmd)) {
		free_cache_devices_list(caches, caches_count);
		cas_printf(LOG_INFO, "Error getting cores in pool list\n");
		return FAILURE;
	}

	if (caches == NULL && !core_pool_path_cmd.core_pool_count) {
		cas_printf(LOG_INFO, "No caches running\n");
		return SUCCESS;
	}

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		free(core_pool_path_cmd.core_path_tab);
		free_cache_devices_list(caches, caches_count);
		return FAILURE;
	}

	printout_ctx.intermediate = intermediate_file[0];
	printout_ctx.out = stdout;
	printout_ctx.type = (OUTPUT_FORMAT_CSV == list_format ? RAW_CSV : TEXT);

	if (pthread_create(&thread, 0, list_printout, &printout_ctx)) {
		cas_printf(LOG_ERR,"Failed to create thread.\n");
		free(core_pool_path_cmd.core_path_tab);
		free_cache_devices_list(caches, caches_count);
		fclose(intermediate_file[0]);
		fclose(intermediate_file[1]);
		return FAILURE;
	}

	if (caches_count || core_pool_path_cmd.core_pool_count) {
		fprintf(intermediate_file[1],
			TAG(TREE_HEADER)"%s,%s,%s,%s,%s,%s\n",
			"type", "id", "disk", "status",
			"write policy", "device");
	}

	if (core_pool_path_cmd.core_pool_count) {
		fprintf(intermediate_file[1], TAG(TREE_BRANCH)
			"%s,%s,%s,%s,%s,%s\n",
			"core pool", /* type */
			"-", /* id */
			"-",
			"-",
			"-", /* write policy */
			"-" /* device */);
		for (i = 0; i < core_pool_path_cmd.core_pool_count; i++) {
			char *core_path = core_pool_path_cmd.core_path_tab + (MAX_STR_LEN * i);
			if (!by_id_path) {
				if (get_dev_path(core_path, core_path, MAX_STR_LEN)) {
					cas_printf(LOG_WARNING, "WARNING: Can not resolve path "
						   "to core. By-id path will be shown for that "
						   "core.\n");
				}
			}
			fprintf(intermediate_file[1], TAG(TREE_LEAF)
			"%s,%s,%s,%s,%s,%s\n",
			"core", /* type */
			"-", /* id */
			core_path,
			"Detached",
			"-", /* write policy */
			"-" /* device */);
		}
	}

	for (i = 0; i < caches_count; ++i) {
		curr_cache = caches[i];

		char status_buf[CACHE_STATE_LENGHT];
		const char *tmp_status;
		char mode_string[12];
		char exp_obj[32];
		char cache_ctrl_dev[MAX_STR_LEN] = "-";
		float cache_flush_prog;
		float core_flush_prog;

		if (!by_id_path && !curr_cache->standby_detached) {
			if (get_dev_path(curr_cache->device, curr_cache->device,
					sizeof(curr_cache->device))) {
				cas_printf(LOG_WARNING, "WARNING: Cannot resolve path "
					"to cache. By-id path will be shown for that cache.\n");
			}
		}

		cache_flush_prog = calculate_flush_progress(curr_cache->dirty, curr_cache->flushed);
		if (cache_flush_prog) {
			snprintf(status_buf, sizeof(status_buf),
				"%s (%3.1f %%)", "Flushing", cache_flush_prog);
			tmp_status = status_buf;
			snprintf(mode_string, sizeof(mode_string), "wb->%s",
					cache_mode_to_name(curr_cache->mode));
		} else {
			tmp_status = get_cache_state_name(curr_cache->state, curr_cache->standby_detached);

			if (curr_cache->state & (1 << ocf_cache_state_standby)) {
				strncpy(mode_string, "-", sizeof(mode_string));
				if (!curr_cache->standby_detached) {
					snprintf(cache_ctrl_dev, sizeof(cache_ctrl_dev),
							"/dev/cas-cache-%d", curr_cache->id);
				}
			} else {
				snprintf(mode_string, sizeof(mode_string), "%s",
						cache_mode_to_name(curr_cache->mode));
			}
		}

		fprintf(intermediate_file[1], TAG(TREE_BRANCH)
			"%s,%u,%s,%s,%s,%s\n",
			"cache", /* type */
			curr_cache->id, /* id */
			curr_cache->standby_detached ? "-" : curr_cache->device, /* device path */
			tmp_status, /* cache status */
			mode_string, /* write policy */
			cache_ctrl_dev  /* device */);

		for (j = 0; j < curr_cache->core_count; ++j) {
			char* core_path;

			curr_core = &curr_cache->cores[j];
			core_path = curr_core->path;

			core_flush_prog = calculate_flush_progress(curr_core->info.info.dirty,
					curr_core->info.info.flushed);

			if (!core_flush_prog && cache_flush_prog) {
				core_flush_prog = curr_core->info.info.dirty ? 0 : 100;
			}

			if (core_flush_prog || cache_flush_prog) {
				snprintf(status_buf, CACHE_STATE_LENGHT,
						"%s (%3.1f %%)", "Flushing", core_flush_prog);
				tmp_status = status_buf;
			} else {
				tmp_status = get_core_state_name(curr_core->info.state);
			}

			snprintf(exp_obj, sizeof(exp_obj), "/dev/cas%d-%d",
					curr_cache->id, curr_core->id);

			fprintf(intermediate_file[1], TAG(TREE_LEAF)
					"%s,%u,%s,%s,%s,%s\n",
					"core", /* type */
					curr_core->id, /* id */
					core_path, /* path to core*/
					tmp_status, /* core status */
					"-", /* write policy */
					curr_core->info.exp_obj_exists ? exp_obj : "-" /* exported object path */);
		}
	}

	free_cache_devices_list(caches, caches_count);
	free(core_pool_path_cmd.core_path_tab);

	fclose(intermediate_file[1]);
	pthread_join(thread, 0);
	if (printout_ctx.result) {
		result = 1;
		cas_printf(LOG_ERR, "An error occured during list formatting.\n");

	}
	fclose(intermediate_file[0]);
	return result;
}

int _check_cache_device(const char *device_path,
		struct kcas_cache_check_device *cmd_info)
{
	int result, fd;

	if (strncpy_s(cmd_info->path_name, sizeof(cmd_info->path_name),
			device_path, MAX_STR_LEN)) {
		return FAILURE;
	}

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	result = run_ioctl(fd, KCAS_IOCTL_CACHE_CHECK_DEVICE, cmd_info);

	close(fd);

	return result ? FAILURE : SUCCESS;
}

int check_cache_device(const char *device_path)
{
	struct kcas_cache_check_device cmd_info = {};
	FILE *intermediate_file[2];
	int result;

	if (set_device_path(cmd_info.path_name, sizeof(cmd_info.path_name),
			    device_path, MAX_STR_LEN) != SUCCESS)
		return FAILURE;

	result = _check_cache_device(device_path, &cmd_info);

	if (result) {
		result = cmd_info.ext_err_code ? : KCAS_ERR_SYSTEM;
		print_err(result);
		return FAILURE;
	}

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		return FAILURE;
	}

	fprintf(intermediate_file[1], TAG(TABLE_HEADER) "Is cache,Clean Shutdown,Cache dirty\n");

	fprintf(intermediate_file[1], TAG(TABLE_ROW));
	if (cmd_info.is_cache_device && cmd_info.metadata_compatible) {
		fprintf(intermediate_file[1], "yes,%s,%s\n",
				cmd_info.clean_shutdown ? "yes" : "no",
				cmd_info.cache_dirty ? "yes" : "no");
	} else {
		fprintf(intermediate_file[1], "no,-,-\n");
	}

	fclose(intermediate_file[1]);
	stat_format_output(intermediate_file[0], stdout, RAW_CSV);
	fclose(intermediate_file[0]);

	return SUCCESS;
}

int zero_md(const char *cache_device, bool force)
{
	struct kcas_cache_check_device cmd_info = {};
	char zero_page[4096] = {0};
	int fd = 0;
	int result;

	/* check if device is available */
	fd = open(cache_device, O_WRONLY | O_SYNC | O_EXCL);
	if (fd < 0) {
		cas_printf(LOG_ERR, "Error while opening '%s'exclusively. This can be due to\n"
				    "cache instance running on this device. In such case please "
				    "stop the cache and try again.\n", cache_device);
		return FAILURE;
	}
	close(fd);

	result = _check_cache_device(cache_device, &cmd_info);
	if (result == FAILURE) {
		cas_printf(LOG_ERR, "Failed to retrieve device's information.\n");
		return FAILURE;
	}

	/* don't delete metadata if device hasn't got CAS's metadata */
	if (!cmd_info.is_cache_device) {
		cas_printf(LOG_ERR, "Device '%s' does not contain OpenCAS's metadata.\n", cache_device);
		return FAILURE;
	}

	if (!cmd_info.clean_shutdown) {
		if (!force) {
			cas_printf(LOG_ERR, "Cache instance did not shut down cleanly. It might contain dirty data. \n"
					"Clearing metadata might result in loss of dirty data. Please recover cache instance\n"
					"by loading it and flush dirty data in order to preserve them on the core device.\n"
					"Alternatively, if you wish to clear metadata anyway, please use '--force' option. \n");
			return FAILURE;
		} else {
			cas_printf(LOG_WARNING, "Clearing metadata after dirty shutdown - potential loss of dirty data.\n");
		}
	} else if (cmd_info.cache_dirty) {
		if (!force) {
			cas_printf(LOG_ERR, "Cache instance contains dirty data. Clearing metadata will result in loss of dirty data.\n"
					"Please load cache instance and flush dirty data in order to preserve them on the core device.\n"
					"Alternatively, if you wish to clear metadata anyway, please use '--force' option. \n");
			return FAILURE;
		} else {
			cas_printf(LOG_WARNING, "Clearing metadata for dirty pages - dirty cache data is being discarded. \n");
		}
	}

	fd = open(cache_device, O_WRONLY | O_SYNC | O_EXCL);
	if (fd < 0) {
		cas_printf(LOG_ERR, "Error while opening '%s'exclusively. This can be due to\n"
				    "cache instance running on this device. In such case please\n"
				    "stop the cache and try again.\n", cache_device);
		return FAILURE;
	}

	if(write(fd, zero_page, 4096) != 4096) {
		close(fd);
		cas_printf(LOG_ERR, "Error while wiping out metadata from device '%s'.\n", cache_device);
		return FAILURE;
	}

	close(fd);
	cas_printf(LOG_INFO, "OpenCAS's metadata wiped succesfully from device '%s'.\n", cache_device);
	return SUCCESS;
}

int cas_ioctl(int id, void *data)
{
	int fd, result;

	fd = open_ctrl_device();
	if (fd == -1)
		return FAILURE;

	result = run_ioctl(fd, id, data);
	close(fd);

	return result < 0 ? FAILURE : SUCCESS;
}


int standby_init(int cache_id, ocf_cache_line_size_t line_size,
		const char *cache_device, int force)
{
	return start_cache(cache_id,
			CACHE_INIT_STANDBY_NEW,
			cache_device,
			ocf_cache_mode_default,
			line_size,
			force);
}

int standby_load(int cache_id, ocf_cache_line_size_t line_size,
		const char *cache_device)
{
	return start_cache(cache_id,
			CACHE_INIT_STANDBY_LOAD,
			cache_device,
			ocf_cache_mode_none,
			line_size,
			0);
}

int standby_detach(int cache_id)
{
	struct kcas_standby_detach cmd = {
		.cache_id = cache_id
	};

	if (cas_ioctl(KCAS_IOCTL_STANDBY_DETACH, &cmd) != SUCCESS) {
		print_err(cmd.ext_err_code ? : KCAS_ERR_SYSTEM);
		return FAILURE;
	}

	cas_printf(LOG_INFO, "Successfully detached cache instance %hu\n",
			cache_id);

	return SUCCESS;
}

int standby_activate(int cache_id, const char *cache_device)
{
	int fd = 0;
	struct kcas_standby_activate cmd = {
		.cache_id = cache_id
	};

	if (set_device_path(cmd.cache_path, sizeof(cmd.cache_path),
			    cache_device, MAX_STR_LEN) != SUCCESS) {
		return FAILURE;
	}

	if (cas_ioctl(KCAS_IOCTL_STANDBY_ACTIVATE, &cmd) != SUCCESS) {
		cas_printf(LOG_ERR, "Error activating cache %d\n", cache_id);
		if (abs(cmd.ext_err_code) == OCF_ERR_NOT_OPEN_EXC) {
			cas_printf(LOG_ERR, "Cannot open the device exclusively. Make sure "
					"to detach cache before activation.\n");
		} else {
			print_err(cmd.ext_err_code ? : KCAS_ERR_SYSTEM);
		}
		return FAILURE;
	}

	fd = open_ctrl_device();
	if(fd == -1)
		return FAILURE;

	check_cache_state_incomplete(cache_id, fd);
	close(fd);

	cas_printf(LOG_INFO, "Successfully activated cache instance %hu\n",
			cache_id);

	return SUCCESS;
}
