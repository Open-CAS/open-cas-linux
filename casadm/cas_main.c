/*
* Copyright(c) 2012-2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <fstab.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <linux/fs.h>
#include "argp.h"
#include "cas_lib.h"
#include "cas_lib_utils.h"
#include "safeclib/safe_str_lib.h"
#include <cas_ioctl_codes.h>
#include "upgrade.h"
#include "statistics_view.h"

#define HELP_HEADER OCF_PREFIX_LONG

#define WRONG_DEVICE_ERROR "Specified caching device '%s' is not supported.\n"
#define NOT_BLOCK_ERROR    "Please use block device file.\n"

extern cas_printf_t cas_printf;

#define PARAM_TYPE_CORE		1
#define PARAM_TYPE_CACHE	2

/* struct with all the commands parameters/flags with default values */
struct command_args{
	int force;
	int cache_id;
	int core_id;
	int state;
	int cache_mode;
	int stats_filters;
	int output_format;
	int io_class_id;
	int eviction_policy_type;
	int line_size;
	int cache_state_flush;
	int flush_data;
	int cleaning_policy_type;
	int promotion_policy_type;
	int script_subcmd;
	int try_add;
	int update_path;
	int detach;
	int no_flush;
	const char* cache_device;
	const char* core_device;
	uint32_t params_type;
	uint32_t params_count;
	bool verbose;
};

static struct command_args command_args_values = {
		.force = 0,
		.cache_id = OCF_CACHE_ID_INVALID,
		.core_id = OCF_CORE_ID_INVALID,
		.state = CACHE_INIT_NEW,
		.cache_mode = ocf_cache_mode_default,
		.stats_filters = STATS_FILTER_DEFAULT,
		.output_format = OUTPUT_FORMAT_DEFAULT,
		.io_class_id = OCF_IO_CLASS_INVALID,
		.line_size = ocf_cache_line_size_default,
		.cache_state_flush = UNDEFINED, /* three state logic: YES NO UNDEFINED */
		.flush_data = 1,
		.cleaning_policy_type = 0,
		.promotion_policy_type = 0,
		.script_subcmd = -1,
		.try_add = false,
		.update_path = false,
		.detach = false,
		.no_flush = false,
		.cache_device = NULL,
		.core_device = NULL,

		.params_type = 0,
		.params_count = 0,
		.verbose = false,
};

int validate_device_name(const char *dev_name) {
	if (validate_dev(dev_name)) {
		cas_printf(LOG_ERR, "Cache creation aborted, %s entry exists in /etc/fstab. Please remove it!\n",
				dev_name);
		return FAILURE;
	}

	if (strnlen(dev_name, MAX_STR_LEN) >= MAX_STR_LEN) {
		cas_printf(LOG_ERR, "Illegal device %s\n", dev_name);
		return FAILURE;
	}

	return SUCCESS;
}

int command_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN,
				OCF_CACHE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "core-id")) {
		if (validate_str_num(arg[0], "core id", 0, OCF_CORE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.core_id = atoi(arg[0]);
	} else if (!strcmp(opt, "core-device")) {
		if (validate_device_name(arg[0]) == FAILURE)
			return FAILURE;

		command_args_values.core_device = arg[0];
	} else if (!strcmp(opt, "cache-device")) {
		if (validate_device_name(arg[0]) == FAILURE)
			return FAILURE;

		command_args_values.cache_device = arg[0];
	} else if (!strcmp(opt, "no-data-flush")) {
		command_args_values.flush_data = 0;
	} else if (!strcmp(opt, "output-format")) {
		command_args_values.output_format
			= validate_str_output_format(arg[0]);

		if (OUTPUT_FORMAT_INVALID == command_args_values.output_format)
			return FAILURE;
	} else if (!strcmp(opt, "cleaning-policy-type")) {
		command_args_values.cleaning_policy_type = validate_str_cln_policy((const char*)arg[0]);

		if (command_args_values.cleaning_policy_type < 0)
			return FAILURE;
	} else if (!strcmp(opt, "eviction-policy")) {
		command_args_values.eviction_policy_type = validate_str_ev_policy((const char*)arg[0]);

		if (command_args_values.eviction_policy_type < 0)
			return FAILURE;
	} else if (!strcmp(opt, "try-add")) {
		command_args_values.try_add = true;
	} else if (!strcmp(opt, "update-path")) {
		command_args_values.update_path = true;
	} else if (!strcmp(opt, "detach")) {
		command_args_values.detach = true;
	} else if (!strcmp(opt, "no-flush")) {
		command_args_values.no_flush = true;
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int remove_core_command_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "cache-id")){
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN, OCF_CACHE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "core-id")){
		if (validate_str_num(arg[0], "core id", 0, OCF_CORE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.core_id = atoi(arg[0]);
	} else if (!strcmp(opt, "force")){
		command_args_values.force = 1;
	}

	return 0;
}

int core_pool_remove_command_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "device")) {
		if (strnlen_s(arg[0], MAX_STR_LEN) >= MAX_STR_LEN) {
			cas_printf(LOG_ERR, "Illegal device %s\n", arg[0]);
			return FAILURE;
		}

		command_args_values.core_device = arg[0];
	}

	return 0;
}

int start_cache_command_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "force")) {
		command_args_values.force = 1;
	} else if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN, OCF_CACHE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "load")) {
		command_args_values.state = CACHE_INIT_LOAD;
	} else if (!strcmp(opt, "cache-device")) {
		if(validate_device_name(arg[0]) == FAILURE)
			return FAILURE;

		command_args_values.cache_device = arg[0];
	} else if (!strcmp(opt, "cache-mode")) {
		command_args_values.cache_mode =
				validate_str_cache_mode((const char*)arg[0]);

		if (command_args_values.cache_mode < 0)
			return FAILURE;
	} else if (!strcmp(opt, "cache-line-size")) {
		if (validate_str_num_sbd(arg[0], "cache line size", ocf_cache_line_size_min / KiB,
				ocf_cache_line_size_max / KiB) == FAILURE)
			return FAILURE;

		command_args_values.line_size = atoi((const char*)arg[0]) * KiB;
	}

	return 0;
}

#define xstr(s) str(s)
#define str(s) #s

#define CACHE_ID_DESC "Identifier of cache instance <"xstr(OCF_CACHE_ID_MIN)"-"xstr(OCF_CACHE_ID_MAX)">"
#define CACHE_ID_DESC_LONG CACHE_ID_DESC " (if not provided, the first available number will be used)"

/* OCF_CORE_ID_MAX is defined by arithmetic operations on OCF_CORE_MAX. As a result there is no easy way
 * to stringify OCF_CORE_ID_MAX. To work around this, additional definition for max core id is introduced here.
 * In case of mismatch between header and local definition preprocessor error is triggered. */
#define _CASADM_CORE_ID_MAX 4095
#if (_CASADM_CORE_ID_MAX != OCF_CORE_ID_MAX)
#error "Max core id definitions discrepancy. Please update above definition."
#endif
#define CORE_ID_DESC "Identifier of core <0-"xstr(_CASADM_CORE_ID_MAX)"> within given cache instance"

#define CACHE_DEVICE_DESC "Caching device to be used"
#define CORE_DEVICE_DESC "Path to core device"


static cli_option start_options[] = {
	{'d', "cache-device", CACHE_DEVICE_DESC, 1, "DEVICE", CLI_OPTION_REQUIRED},
	{'i', "cache-id", CACHE_ID_DESC_LONG, 1, "ID", 0},
	{'l', "load", "Load cache metadata from caching device (DANGEROUS - see manual or Admin Guide for details)"},
	{'f', "force", "Force the creation of cache instance"},
	{'c', "cache-mode", "Set cache mode from available: {"CAS_CLI_HELP_START_CACHE_MODES"} "CAS_CLI_HELP_START_CACHE_MODES_FULL"; without this parameter Write-Through will be set by default", 1, "NAME"},
	{'x', "cache-line-size", "Set cache line size in kibibytes: {4,8,16,32,64}[KiB] (default: %d)", 1, "NUMBER",  CLI_OPTION_DEFAULT_INT, 0, 0, ocf_cache_line_size_default / KiB},
	{0}
};

static int check_fs(const char* device)
{
	char cache_dev_path[MAX_STR_LEN];
	static const char fsck_cmd[] = "/sbin/fsck -n %s > /dev/null 2>&1";
	static const uint32_t size = MAX_STR_LEN + sizeof(fsck_cmd) + 1;
	char buff[size];

	if (get_dev_path(device, cache_dev_path, sizeof(cache_dev_path))) {
		cas_printf(LOG_ERR, "Device does not exist\n");
		return FAILURE;
	}

	snprintf(buff, sizeof(buff), fsck_cmd, cache_dev_path);

	if (!system(buff)) {
		if (command_args_values.force) {
			cas_printf(LOG_INFO, "A filesystem existed on %s. "
				"Data may have been lost\n",
				device);
		} else {
			/* file system on cache device */
			cas_printf(LOG_ERR, "A filesystem exists on %s. "
				"Specify the --force option if you "
				"wish to add the cache anyway.\n"
				"Note: this may result in loss of data\n",
				device);
			return FAILURE;
		}
	}

	return SUCCESS;
}

int handle_start()
{
	int cache_device = 0;
	int status;
	struct stat device_info;

	cache_device = open(command_args_values.cache_device, O_RDONLY);

	if (cache_device < 0) {
		cas_printf(LOG_ERR, "Couldn't open cache device %s.\n",
			command_args_values.cache_device);
		return FAILURE;
	}

	if (fstat(cache_device, &device_info)) {
		close(cache_device);
		cas_printf(LOG_ERR, "Could not stat target device:%s!\n",
			command_args_values.cache_device);
		return FAILURE;
	}

	if (!S_ISBLK(device_info.st_mode)) {
		close(cache_device);
		cas_printf(LOG_ERR, WRONG_DEVICE_ERROR NOT_BLOCK_ERROR,
			command_args_values.cache_device);
		return FAILURE;
	}

	if (check_fs(command_args_values.cache_device)) {
		close(cache_device);
		return FAILURE;
	}

	if (close(cache_device) < 0) {
		cas_printf(LOG_ERR, "Couldn't close the cache device.\n");
		return FAILURE;
	}

	status = start_cache(command_args_values.cache_id,
			command_args_values.state,
			command_args_values.cache_device,
			command_args_values.cache_mode,
			command_args_values.eviction_policy_type,
			command_args_values.line_size,
			command_args_values.force);

	return status;
}

static cli_option list_options[] = {
	{'o', "output-format", "Output format: {table|csv}", 1, "FORMAT", 0},
	{0}
};

int handle_list()
{
	return list_caches(command_args_values.output_format);
}

static cli_option stats_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'j', "core-id", "Limit display of core-specific statistics to only ones pertaining to a specific core. If this option is not given, casadm will display statistics pertaining to all cores assigned to given cache instance.", 1, "ID", 0},
	{'d', "io-class-id", "Display per IO class statistics", 1, "ID", CLI_OPTION_OPTIONAL_ARG},
	{'f', "filter", "Apply filters from the following set: {all, conf, usage, req, blk, err}", 1, "FILTER-SPEC"},
	{'o', "output-format", "Output format: {table|csv}", 1, "FORMAT"},
	{0}
};

int stats_command_handle_option(char *opt, const char **arg)
{
	int stats_filters;

	if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN,
				OCF_CACHE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "core-id")) {
		if (validate_str_num(arg[0], "core id", 0,
				     OCF_CORE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.core_id = atoi(arg[0]);
	} else if (!strcmp(opt, "io-class-id")) {
		if (NULL != arg[0]) {
			if (validate_str_num(arg[0], "IO class id",
				     0, OCF_IO_CLASS_ID_MAX) == FAILURE)
				return FAILURE;

			command_args_values.io_class_id = atoi(arg[0]);
		}
		command_args_values.stats_filters |= STATS_FILTER_IOCLASS;
	} else if (!strcmp(opt, "filter")) {
		stats_filters = validate_str_stats_filters(arg[0]);
		if (STATS_FILTER_INVALID == stats_filters)
			return FAILURE;
		stats_filters |= (command_args_values.stats_filters & STATS_FILTER_IOCLASS);
		command_args_values.stats_filters = stats_filters;
	} else if (!strcmp(opt, "output-format")) {
		command_args_values.output_format = validate_str_output_format(arg[0]);
		if (OUTPUT_FORMAT_INVALID == command_args_values.output_format)
			return FAILURE;
	} else {
		return FAILURE;
	}

	return 0;
}

int handle_stats()
{
	return cache_status(command_args_values.cache_id,
			    command_args_values.core_id,
			    command_args_values.io_class_id,
			    command_args_values.stats_filters,
			    command_args_values.output_format);
}

static cli_option stop_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'n', "no-data-flush", "Do not flush dirty data (may be dangerous)"},
	{0}
};

int handle_stop()
{
	return stop_cache(command_args_values.cache_id,
			command_args_values.flush_data);
}

/*****************************************************************************
 *                           GET/SET PARAM HELPERS                           *
 *****************************************************************************/

#define SELECT_PARAM(_array, _index) ({ \
	_array[_index].select = true; \
})

#define SELECT_CORE_PARAM(_index) \
	SELECT_PARAM(cas_core_params, _index)

#define SELECT_CACHE_PARAM(_index) \
	SELECT_PARAM(cas_cache_params, _index)

#define SET_PARAM(_array, _index, _value) ({ \
	SELECT_PARAM(_array, _index); \
	_array[_index].value = _value; \
	command_args_values.params_count++; \
})

#define SET_CORE_PARAM(_index, _value) \
	SET_PARAM(cas_core_params, _index, _value)

#define SET_CACHE_PARAM(_index, _value) \
	SET_PARAM(cas_cache_params, _index, _value)

#define CORE_PARAMS_NS_BEGIN(_name, _desc) { \
	.name = _name, \
	.desc = _desc, \
	.options = { \
		{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED}, \
		{'j', "core-id", CORE_ID_DESC, 1, "ID"},

#define CORE_PARAMS_NS_END() \
		{0}, \
	},\
},

#define GET_CORE_PARAMS_NS(_name, _desc) { \
	.name = _name, \
	.desc = _desc, \
	.options = { \
		{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED}, \
		{'j', "core-id", CORE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED}, \
		{'o', "output-format", "Output format: {table|csv}", 1, "FORMAT"}, \
	CORE_PARAMS_NS_END()

#define CACHE_PARAMS_NS_BEGIN(_name, _desc) { \
	.name = _name, \
	.desc = _desc, \
	.options = { \
		{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED}, \

#define CACHE_PARAMS_NS_END() \
		{0}, \
	},\
},

#define GET_CACHE_PARAMS_NS(_name, _desc) \
	CACHE_PARAMS_NS_BEGIN(_name, _desc) \
		{'o', "output-format", "Output format: {table|csv}", 1, "FORMAT"}, \
	CACHE_PARAMS_NS_END()


static int core_param_handle_option_generic(char *opt, const char **arg, int (*handler)(char *opt, const char **arg))
{
	command_args_values.params_type = PARAM_TYPE_CORE;

	if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN,
				OCF_CACHE_ID_MAX) == FAILURE) {
			return FAILURE;
		}

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "core-id")) {
		if (validate_str_num(arg[0], "core id", OCF_CORE_ID_MIN,
				OCF_CORE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.core_id = atoi(arg[0]);
	} else {
		return handler ? handler(opt, arg) : FAILURE;
	}

	return SUCCESS;
}

static int cache_param_handle_option_generic(char *opt, const char **arg, int (*handler)(char *opt, const char **arg))
{
	command_args_values.params_type = PARAM_TYPE_CACHE;

	if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN,
				OCF_CACHE_ID_MAX) == FAILURE) {
			return FAILURE;
		}

		command_args_values.cache_id = atoi(arg[0]);
	} else {
		return handler ? handler(opt, arg) : FAILURE;
	}

	return SUCCESS;
}

/*****************************************************************************
 *                           PARAMS DEFINITIONS                              *
 *****************************************************************************/

uint32_t seq_cutoff_threshold_transform(uint32_t value)
{
	return value / KiB;
}

static char *seq_cutoff_policy_values[] = {
	[ocf_seq_cutoff_policy_always] = "always",
	[ocf_seq_cutoff_policy_full] = "full",
	[ocf_seq_cutoff_policy_never] = "never",
	NULL,
};

static struct cas_param cas_core_params[] = {
	/* Sequential cutoff params */
	[core_param_seq_cutoff_threshold] = {
		.name = "Sequential cutoff threshold [KiB]" ,
		.transform_value = seq_cutoff_threshold_transform,
	},
	[core_param_seq_cutoff_policy] = {
		.name = "Sequential cutoff policy",
		.value_names = seq_cutoff_policy_values,
	},
	{0},
};

static char *cleaning_policy_type_values[] = {
	[ocf_cleaning_nop] = "nop",
	[ocf_cleaning_alru] = "alru",
	[ocf_cleaning_acp] = "acp",
	NULL,
};

static char *promotion_policy_type_values[] = {
	[ocf_promotion_always] = "always",
	[ocf_promotion_nhit] = "nhit",
	NULL,
};

static struct cas_param cas_cache_params[] = {
	/* Cleaning policy type */
	[cache_param_cleaning_policy_type] = {
		.name = "Cleaning policy type" ,
		.value_names = cleaning_policy_type_values,
	},

	/* Cleaning policy ALRU params */
	[cache_param_cleaning_alru_wake_up_time] = {
		.name = "Wake up time [s]" ,
	},
	[cache_param_cleaning_alru_stale_buffer_time] = {
		.name = "Stale buffer time [s]" ,
	},
	[cache_param_cleaning_alru_flush_max_buffers] = {
		.name = "Flush max buffers" ,
	},
	[cache_param_cleaning_alru_activity_threshold] = {
		.name = "Activity threshold [ms]" ,
	},

	/* Cleaning policy ACP params */
	[cache_param_cleaning_acp_wake_up_time] = {
		.name = "Wake up time [ms]" ,
	},
	[cache_param_cleaning_acp_flush_max_buffers] = {
		.name = "Flush max buffers" ,
	},

	/* Promotion policy type */
	[cache_param_promotion_policy_type] = {
		.name = "Promotion policy type",
		.value_names = promotion_policy_type_values,
	},

	/*Promotion policy NHIT params */
	[cache_param_promotion_nhit_insertion_threshold] = {
		.name = "Insertion threshold",
	},
	[cache_param_promotion_nhit_trigger_threshold] = {
		.name = "Policy trigger [%]",
	},
	{0},
};

/*****************************************************************************
 *                           SET PARAM NAMESPACE                             *
 *****************************************************************************/

#define SEQ_CUT_OFF_THRESHOLD_DESC "Sequential cutoff activation threshold [KiB]"
#define SEQ_CUT_OFF_POLICY_DESC "Sequential cutoff policy. " \
	"Available policies: {always|full|never}"

#define CLEANING_POLICY_TYPE_DESC "Cleaning policy type. " \
	"Available policy types: {nop|alru|acp}"

#define CLEANING_ALRU_WAKE_UP_DESC "Period of time between awakenings of flushing thread <%d-%d>[s] (default: %d s)"
#define CLEANING_ALRU_STALENESS_TIME_DESC "Time that has to pass from the last write operation before a dirty cache" \
	 " block can be scheduled to be flushed <%d-%d>[s] (default: %d s)"
#define CLEANING_ALRU_FLUSH_MAX_BUFFERS_DESC "Number of dirty cache blocks to be flushed in one cleaning cycle" \
	" <%d-%d> (default: %d)"
#define CLEANING_ALRU_ACTIVITY_THRESHOLD_DESC "Cache idle time before flushing thread can start <%d-%d>[ms]" \
	" (default: %d ms)"

#define CLEANING_ACP_WAKE_UP_DESC "Time between ACP cleaning thread iterations <%d-%d>[ms] (default: %d ms)"
#define CLEANING_ACP_MAX_BUFFERS_DESC "Number of cache lines flushed in single ACP cleaning thread iteration" \
	" <%d-%d> (default: %d)"

#define PROMOTION_POLICY_TYPE_DESC "Promotion policy type. "\
	"Available policy types: {always|nhit}"

#define PROMOTION_NHIT_TRIGGER_DESC "Cache occupancy value over which NHIT promotion is active " \
	"<%d-%d>[%] (default: %d%)"

#define PROMOTION_NHIT_THRESHOLD_DESC "Number of requests for given core line " \
	"after which NHIT policy allows insertion into cache <%d-%d> (default: %d)"

static cli_namespace set_param_namespace = {
	.short_name = 'n',
	.long_name = "name",
	.entries = {
		CORE_PARAMS_NS_BEGIN("seq-cutoff", "Sequential cutoff parameters")
			{'t', "threshold", SEQ_CUT_OFF_THRESHOLD_DESC, 1, "KiB", 0},
			{'p', "policy", SEQ_CUT_OFF_POLICY_DESC, 1, "POLICY", 0},
		CORE_PARAMS_NS_END()

		CACHE_PARAMS_NS_BEGIN("cleaning", "Cleaning policy parameters")
			{'p', "policy", CLEANING_POLICY_TYPE_DESC, 1, "POLICY", 0},
		CACHE_PARAMS_NS_END()

		CACHE_PARAMS_NS_BEGIN("promotion", "Promotion policy parameters")
			{'p', "policy", PROMOTION_POLICY_TYPE_DESC, 1, "POLICY", 0},
		CACHE_PARAMS_NS_END()

		CACHE_PARAMS_NS_BEGIN("promotion-nhit", "Promotion policy NHIT parameters")
			{'t', "threshold", PROMOTION_NHIT_THRESHOLD_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_NHIT_MIN_THRESHOLD, OCF_NHIT_MAX_THRESHOLD,
				OCF_NHIT_THRESHOLD_DEFAULT},
			{'o', "trigger", PROMOTION_NHIT_TRIGGER_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_NHIT_MIN_TRIGGER, OCF_NHIT_MAX_TRIGGER,
				OCF_NHIT_TRIGGER_DEFAULT},
		CACHE_PARAMS_NS_END()

		CACHE_PARAMS_NS_BEGIN("cleaning-alru", "Cleaning policy ALRU parameters")
			{'w', "wake-up", CLEANING_ALRU_WAKE_UP_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ALRU_MIN_WAKE_UP, OCF_ALRU_MAX_WAKE_UP,
				OCF_ALRU_DEFAULT_WAKE_UP},
			{'s', "staleness-time", CLEANING_ALRU_STALENESS_TIME_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ALRU_MIN_STALENESS_TIME, OCF_ALRU_MAX_STALENESS_TIME,
				OCF_ALRU_DEFAULT_STALENESS_TIME},
			{'b', "flush-max-buffers", CLEANING_ALRU_FLUSH_MAX_BUFFERS_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ALRU_MIN_FLUSH_MAX_BUFFERS, OCF_ALRU_MAX_FLUSH_MAX_BUFFERS,
				OCF_ALRU_DEFAULT_FLUSH_MAX_BUFFERS},
			{'t', "activity-threshold", CLEANING_ALRU_ACTIVITY_THRESHOLD_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ALRU_MIN_ACTIVITY_THRESHOLD, OCF_ALRU_MAX_ACTIVITY_THRESHOLD,
				OCF_ALRU_DEFAULT_ACTIVITY_THRESHOLD},
		CACHE_PARAMS_NS_END()

		CACHE_PARAMS_NS_BEGIN("cleaning-acp", "Cleaning policy ACP parameters")
			{'w', "wake-up", CLEANING_ACP_WAKE_UP_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ACP_MIN_WAKE_UP, OCF_ACP_MAX_WAKE_UP,
				OCF_ACP_DEFAULT_WAKE_UP},
			{'b', "flush-max-buffers", CLEANING_ACP_MAX_BUFFERS_DESC, 1, "NUMBER",
				CLI_OPTION_RANGE_INT | CLI_OPTION_DEFAULT_INT,
				OCF_ACP_MIN_FLUSH_MAX_BUFFERS, OCF_ACP_MAX_FLUSH_MAX_BUFFERS,
				OCF_ACP_DEFAULT_FLUSH_MAX_BUFFERS},
		CACHE_PARAMS_NS_END()

		{0},
	},
};

int set_param_seq_cutoff_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "threshold")) {
		if (validate_str_num(arg[0], "sequential cutoff threshold", 1,
				4194181) == FAILURE)
			return FAILURE;

		SET_CORE_PARAM(core_param_seq_cutoff_threshold, atoi(arg[0]) * KiB);
	} else if (!strcmp(opt, "policy")) {
		if (!strcmp("always", arg[0])) {
			SET_CORE_PARAM(core_param_seq_cutoff_policy,
					ocf_seq_cutoff_policy_always);
		} else if (!strcmp("full", arg[0])) {
			SET_CORE_PARAM(core_param_seq_cutoff_policy,
					ocf_seq_cutoff_policy_full);
		} else if (!strcmp("never", arg[0])) {
			SET_CORE_PARAM(core_param_seq_cutoff_policy,
					ocf_seq_cutoff_policy_never);
		} else {
			cas_printf(LOG_ERR, "Error: Invalid policy name.\n");
			return FAILURE;
		}
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int set_param_cleaning_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "policy")) {
		if (!strcmp("nop", arg[0])) {
			SET_CACHE_PARAM(cache_param_cleaning_policy_type,
					ocf_cleaning_nop);
		} else if (!strcmp("alru", arg[0])) {
			SET_CACHE_PARAM(cache_param_cleaning_policy_type,
					ocf_cleaning_alru);
		} else if (!strcmp("acp", arg[0])) {
			SET_CACHE_PARAM(cache_param_cleaning_policy_type,
					ocf_cleaning_acp);
		} else {
			cas_printf(LOG_ERR, "Error: Invalid policy name.\n");
			return FAILURE;
		}
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int set_param_cleaning_alru_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "wake-up")) {
		if (validate_str_num(arg[0], "wake-up time",
				OCF_ALRU_MIN_WAKE_UP, OCF_ALRU_MAX_WAKE_UP)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_alru_wake_up_time,
				strtoul(arg[0], NULL, 10));
	} else if (!strcmp(opt, "staleness-time")) {
		if (validate_str_num(arg[0], "staleness time",
				OCF_ALRU_MIN_STALENESS_TIME, OCF_ALRU_MAX_STALENESS_TIME)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_alru_stale_buffer_time,
				strtoul(arg[0], NULL, 10));
	} else if (!strcmp(opt, "flush-max-buffers")) {
		if (validate_str_num(arg[0], "flush max buffers",
				OCF_ALRU_MIN_FLUSH_MAX_BUFFERS, OCF_ALRU_MAX_FLUSH_MAX_BUFFERS)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_alru_flush_max_buffers,
				strtoul(arg[0], NULL, 10));
	} else if (!strcmp(opt, "activity-threshold")) {
		if (validate_str_num(arg[0], "activity threshold",
				OCF_ALRU_MIN_ACTIVITY_THRESHOLD, OCF_ALRU_MAX_ACTIVITY_THRESHOLD)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_alru_activity_threshold,
				strtoul(arg[0], NULL, 10));
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int set_param_cleaning_acp_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "wake-up")) {
		if (validate_str_num(arg[0], "wake-up time",
				OCF_ACP_MIN_WAKE_UP, OCF_ACP_MAX_WAKE_UP)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_acp_wake_up_time,
				strtoul(arg[0], NULL, 10));
	} else if (!strcmp(opt, "flush-max-buffers")) {
		if (validate_str_num(arg[0], "flush max buffers",
				OCF_ACP_MIN_FLUSH_MAX_BUFFERS, OCF_ACP_MAX_FLUSH_MAX_BUFFERS)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_cleaning_acp_flush_max_buffers,
				strtoul(arg[0], NULL, 10));
	}

	return SUCCESS;
}

int set_param_promotion_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "policy")) {
		if (!strcmp("always", arg[0])) {
			SET_CACHE_PARAM(cache_param_promotion_policy_type,
					ocf_promotion_always);
		} else if (!strcmp("nhit", arg[0])) {
			SET_CACHE_PARAM(cache_param_promotion_policy_type,
					ocf_promotion_nhit);
		} else {
			cas_printf(LOG_ERR, "Error: Invalid policy name.\n");
			return FAILURE;
		}
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int set_param_promotion_nhit_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "threshold")) {
		if (validate_str_num(arg[0], "threshold",
				OCF_NHIT_MIN_THRESHOLD, OCF_NHIT_MAX_THRESHOLD)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_promotion_nhit_insertion_threshold,
				strtoul(arg[0], NULL, 10));
	} else if (!strcmp(opt, "trigger")) {
		if (validate_str_num(arg[0], "trigger",
				OCF_NHIT_MIN_TRIGGER, OCF_NHIT_MAX_TRIGGER)) {
			return FAILURE;
		}

		SET_CACHE_PARAM(cache_param_promotion_nhit_trigger_threshold,
				strtoul(arg[0], NULL, 10));
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int set_param_namespace_handle_option(char *namespace, char *opt, const char **arg)
{
	if (!strcmp(namespace, "seq-cutoff")) {
		return core_param_handle_option_generic(opt, arg,
				set_param_seq_cutoff_handle_option);
	} else if (!strcmp(namespace, "cleaning")) {
		return cache_param_handle_option_generic(opt, arg,
				set_param_cleaning_handle_option);
	} else if (!strcmp(namespace, "cleaning-alru")) {
		return cache_param_handle_option_generic(opt, arg,
				set_param_cleaning_alru_handle_option);
	} else if (!strcmp(namespace, "cleaning-acp")) {
		return cache_param_handle_option_generic(opt, arg,
				set_param_cleaning_acp_handle_option);
	} else if (!strcmp(namespace, "promotion")) {
		return cache_param_handle_option_generic(opt, arg,
				set_param_promotion_handle_option);
	} else if (!strcmp(namespace, "promotion-nhit")) {
		return cache_param_handle_option_generic(opt, arg,
				set_param_promotion_nhit_handle_option);
	} else {
		return FAILURE;
	}
}


int handle_set_param()
{
	int err = 0;

	if (command_args_values.params_count == 0) {
		cas_printf(LOG_ERR, "Error: No parameters specified!\n");
		return FAILURE;
	}

	switch (command_args_values.params_type) {
	case PARAM_TYPE_CORE:
		err = core_params_set(command_args_values.cache_id,
				command_args_values.core_id,
				cas_core_params);
		break;
	case PARAM_TYPE_CACHE:
		err = cache_params_set(command_args_values.cache_id,
				cas_cache_params);
		break;
	default:
		err = FAILURE;
		break;
	}

	if (err)
		cas_printf(LOG_ERR, "Setting runtime parameter failed!\n");

	return err;
}

/*****************************************************************************
 *                           GET PARAM NAMESPACE                             *
 *****************************************************************************/

static cli_namespace get_param_namespace = {
	.short_name = 'n',
	.long_name = "name",
	.entries = {
		GET_CORE_PARAMS_NS("seq-cutoff", "Sequential cutoff parameters")
		GET_CACHE_PARAMS_NS("cleaning", "Cleaning policy parameters")
		GET_CACHE_PARAMS_NS("cleaning-alru", "Cleaning policy ALRU parameters")
		GET_CACHE_PARAMS_NS("cleaning-acp", "Cleaning policy ACP parameters")
		GET_CACHE_PARAMS_NS("promotion", "Promotion policy parameters")
		GET_CACHE_PARAMS_NS("promotion-nhit", "Promotion policy NHIT parameters")

		{0},
	},
};

int get_param_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "output-format")) {
		command_args_values.output_format = validate_str_output_format(arg[0]);
		if (OUTPUT_FORMAT_INVALID == command_args_values.output_format)
			return FAILURE;
	} else {
		return FAILURE;
	}

	return SUCCESS;
}

int get_param_namespace_handle_option(char *namespace, char *opt, const char **arg)
{
	if (!strcmp(namespace, "seq-cutoff")) {
		SELECT_CORE_PARAM(core_param_seq_cutoff_threshold);
		SELECT_CORE_PARAM(core_param_seq_cutoff_policy);
		return core_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else if (!strcmp(namespace, "cleaning")) {
		SELECT_CACHE_PARAM(cache_param_cleaning_policy_type);
		return cache_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else if (!strcmp(namespace, "cleaning-alru")) {
		SELECT_CACHE_PARAM(cache_param_cleaning_alru_wake_up_time);
		SELECT_CACHE_PARAM(cache_param_cleaning_alru_stale_buffer_time);
		SELECT_CACHE_PARAM(cache_param_cleaning_alru_flush_max_buffers);
		SELECT_CACHE_PARAM(cache_param_cleaning_alru_activity_threshold);
		return cache_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else if (!strcmp(namespace, "cleaning-acp")) {
		SELECT_CACHE_PARAM(cache_param_cleaning_acp_wake_up_time);
		SELECT_CACHE_PARAM(cache_param_cleaning_acp_flush_max_buffers);
		return cache_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else if (!strcmp(namespace, "promotion")) {
		SELECT_CACHE_PARAM(cache_param_promotion_policy_type);
		return cache_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else if (!strcmp(namespace, "promotion-nhit")) {
		SELECT_CACHE_PARAM(cache_param_promotion_nhit_insertion_threshold);
		SELECT_CACHE_PARAM(cache_param_promotion_nhit_trigger_threshold);
		return cache_param_handle_option_generic(opt, arg,
				get_param_handle_option);
	} else {
		return FAILURE;
	}
}

int handle_get_param()
{
	int format = TEXT;
	int err = 0;

	if (OUTPUT_FORMAT_CSV == command_args_values.output_format) {
		format = RAW_CSV;
	}

	switch (command_args_values.params_type) {
	case PARAM_TYPE_CORE:
		err = core_params_get(command_args_values.cache_id,
				command_args_values.core_id,
				cas_core_params, format);
		break;
	case PARAM_TYPE_CACHE:
		err = cache_params_get(command_args_values.cache_id,
				cas_cache_params, format);
		break;
	default:
		err = FAILURE;
		break;
	}

	if (err)
		cas_printf(LOG_ERR, "Getting runtime parameter failed!\n");

	return err;
}

static cli_option set_state_cache_mode_options[] = {
	{'c', "cache-mode", "Cache mode. Available cache modes: {"CAS_CLI_HELP_SET_CACHE_MODES"}", 1, "NAME", CLI_OPTION_REQUIRED},
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'f', "flush-cache", "Flush all dirty data from cache before switching to new mode. Option is required when switching from Write-Back or Write-Only mode", 1, "yes|no",0},
	{0},
};

int set_cache_mode_command_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "cache-mode")) {
		command_args_values.cache_mode =
				validate_str_cache_mode((const char*)arg[0]);

		if (command_args_values.cache_mode < 0)
			return FAILURE;
	} else if (!strcmp(opt, "cache-id")) {
		if (validate_str_num(arg[0], "cache id", OCF_CACHE_ID_MIN,
				OCF_CACHE_ID_MAX) == FAILURE)
			return FAILURE;

		command_args_values.cache_id = atoi(arg[0]);
	} else if (!strcmp(opt, "flush-cache")) {
		if (!strcmp("yes", arg[0]))
			command_args_values.cache_state_flush = YES;
		else if (!strcmp("no", arg[0]))
			command_args_values.cache_state_flush = NO;
		else {
			cas_printf(LOG_ERR, "Error: 'yes' or 'no' required as an argument for -f option.\n");
			return FAILURE;
		}
	} else {
		return FAILURE;
	}

	return 0;
}

int handle_set_cache_mode()
{
	return set_cache_mode(command_args_values.cache_mode,
			command_args_values.cache_id,
			command_args_values.cache_state_flush);
}

static cli_option add_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'j', "core-id", CORE_ID_DESC, 1, "ID", 0},
	{'d', "core-device", CORE_DEVICE_DESC, 1, "DEVICE", CLI_OPTION_REQUIRED},
	{0}
};

int handle_add()
{
	return add_core(command_args_values.cache_id,
			command_args_values.core_id,
			command_args_values.core_device,
			false, false);
}

static cli_option remove_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'j', "core-id", CORE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'f', "force", "Force remove inactive core"},
	{0}
};

int handle_remove()
{
	return remove_core(command_args_values.cache_id,
			command_args_values.core_id,
			false,
			command_args_values.force);
}

static cli_option core_pool_remove_options[] = {
	{'d', "device", CORE_DEVICE_DESC, 1, "DEVICE", CLI_OPTION_REQUIRED},
	{0}
};

int handle_core_pool_remove()
{
	return core_pool_remove(command_args_values.core_device);
}

#define RESET_COUNTERS_CORE_ID_DESC "Identifier of core <0-"xstr(_CASADM_CORE_ID_MAX) \
		"> within given cache instance. If not specified, statistics are reset " \
		"for all cores in cache instance."

static cli_option reset_counters_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'j', "core-id", RESET_COUNTERS_CORE_ID_DESC, 1, "ID", 0},
	{0}
};

int handle_reset_counters()
{
	return reset_counters(command_args_values.cache_id,
			command_args_values.core_id);
}

static cli_option flush_core_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{'j', "core-id", CORE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{0}
};

int handle_flush_core()
{
	return flush_core(command_args_values.cache_id,
			command_args_values.core_id);
}

static cli_option flush_cache_options[] = {
	{'i', "cache-id", CACHE_ID_DESC, 1, "ID", CLI_OPTION_REQUIRED},
	{0}
};

int handle_flush_cache()
{
	return flush_cache(command_args_values.cache_id);
}

/*******************************************************************************
 * IO Classes Commands
 ******************************************************************************/

enum {
	io_class_opt_subcmd_configure = 0,
	io_class_opt_subcmd_list,

	io_class_opt_cache_id,
	io_class_opt_cache_file_load,
	io_class_opt_output_format,

	io_class_opt_io_class_id,
	io_class_opt_prio,
	io_class_opt_min_size,
	io_class_opt_max_size,
	io_class_opt_name,
	io_class_opt_cache_mode,

	io_class_opt_flag_required,
	io_class_opt_flag_set,

	io_class_opt_subcmd_unknown,
};

/* IO class command options */
static cli_option io_class_params_options[] = {
	[io_class_opt_subcmd_configure] = {
		.short_name = 'C',
		.long_name = "load-config",
		.desc = "Loads configuration for IO classes",
		.args_count = 0,
		.arg = NULL,
		.priv = 0,
		.flags = CLI_OPTION_DEFAULT_INT
	},
	[io_class_opt_subcmd_list] = {
		.short_name = 'L',
		.long_name = "list",
		.desc = "Lists currently configured IO classes",
		.args_count = 0,
		.arg = NULL,
		.priv = 0,
		.flags = CLI_OPTION_DEFAULT_INT,
	},
	[io_class_opt_cache_id] = {
		.short_name = 'i',
		.long_name = "cache-id",
		.desc = CACHE_ID_DESC,
		.args_count = 1,
		.arg = "ID",
		.priv = (1 << io_class_opt_subcmd_configure)
			| (1 << io_class_opt_subcmd_list)
			| (1 << io_class_opt_flag_required),
		.flags = CLI_OPTION_RANGE_INT,
		.max_value = 0,
		.min_value = OCF_CACHE_ID_MAX,
	},
	[io_class_opt_cache_file_load] = {
		.short_name = 'f',
		.long_name = "file",
		.desc = "Configuration file containing IO class definition",
		.args_count = 1,
		.arg = "FILE",
		.priv = (1 << io_class_opt_subcmd_configure)
			| (1 << io_class_opt_flag_required)
	},
	[io_class_opt_output_format] = {
		.short_name = 'o',
		.long_name = "output-format",
		.desc = "Output format: {table|csv}",
		.args_count = 1,
		.arg = "FORMAT",
		.priv = (1 << io_class_opt_subcmd_list)
	},

	[io_class_opt_io_class_id] = {
		.short_name = 'd',
		.long_name = "io-class-id",
		.desc = "IO class ID",
		.args_count = 1,
		.arg = "ID",
		.priv = (1 << io_class_opt_flag_required),
	},
	[io_class_opt_prio] = {
		.short_name = 'p',
		.long_name = "priority",
		.desc = "IO class priority",
		.args_count = 1,
		.arg = xstr(OCF_IO_CLASS_PRIO_HIGHEST)"-"xstr(OCF_IO_CLASS_PRIO_LOWEST),
		.flags = CLI_OPTION_RANGE_INT,
		.min_value = OCF_IO_CLASS_PRIO_HIGHEST,
		.max_value = OCF_IO_CLASS_PRIO_LOWEST,
	},
	[io_class_opt_min_size] = {
		.short_name = 'm',
		.long_name = "min-size",
		.desc = "Guaranteed size of cache space for this IO class",
		.args_count = 1,
		.arg = "SIZE",
	},
	[io_class_opt_max_size] = {
		.short_name = 'x',
		.long_name = "max-size",
		.desc = "Maximum size of cache space for this IO class",
		.args_count = 1,
		.arg = "SIZE",
	},
	[io_class_opt_name] = {
		.short_name = 'n',
		.long_name = "name",
		.desc = "Optional textual name for this IO class",
		.args_count = 1,
		.arg = "NAME",
	},
	[io_class_opt_cache_mode] = {
		.short_name = 'c',
		.long_name = "cache-mode",
		.desc = "Overwrite cache mode for this IO class from available: {"CAS_CLI_HELP_START_CACHE_MODES"}",
		.args_count = 1,
		.arg = "NAME",
	},

	{0}
};

struct {
	int subcmd;
	int cache_id;
	int io_class_id;
	int cache_mode;
	int io_class_prio;
	int output_format;
	uint32_t min;
	uint32_t max;
	char file[MAX_STR_LEN];
	char name[OCF_IO_CLASS_NAME_MAX];
} static io_class_params = {
	.subcmd = io_class_opt_subcmd_unknown,
	.cache_id = 0,
	.file = "",
	.output_format = OUTPUT_FORMAT_DEFAULT
};

/* Filler to print sub-commands */
int io_class_print_subcmd(cli_option* options, int flag)
{
	return (0 == (options->flags & CLI_OPTION_DEFAULT_INT)) ? 0 : 1;
}

/* Filler to print parameters of given sub-command */
int io_class_print_param(cli_option* options, int flag)
{
	return (flag == (options->priv & flag)) ? 1 : 0;
}

static inline void io_class_print_invalid_subcmd(void)
{
	cas_printf(LOG_ERR, "Invalid or missing first sub-command parameter ");
	cas_printf(LOG_ERR, "Expected one of the: {");
	print_options_usage(io_class_params_options, "|", io_class_print_subcmd, 0);
	cas_printf(LOG_INFO, "}\n");
}

/* Parser of option for IO class command */
int io_class_handle_option(char *opt, const char **arg)
{
	if (io_class_opt_subcmd_unknown == io_class_params.subcmd) {
		/* First parameters which defines sub-command */
		if (!strcmp(opt, "load-config")) {
			io_class_params.subcmd = io_class_opt_subcmd_configure;
			return 0;
		} else if (!strcmp(opt, "list")) {
			io_class_params.subcmd = io_class_opt_subcmd_list;
			return 0;
		}
	}

	if (!strcmp(opt, "cache-id")) {
		if (command_handle_option(opt, arg))
			return FAILURE;

		io_class_params_options[io_class_opt_cache_id].priv |= (1 << io_class_opt_flag_set);
		io_class_params.cache_id = command_args_values.cache_id;
	} else if (!strcmp(opt, "file")) {
		if (validate_path(arg[0], 0))
			return FAILURE;

		io_class_params_options[io_class_opt_cache_file_load].priv |=  (1 << io_class_opt_flag_set);

		strncpy_s(io_class_params.file, sizeof(io_class_params.file), arg[0], strnlen_s(arg[0], sizeof(io_class_params.file)));
	} else if (!strcmp(opt, "output-format")) {
		io_class_params.output_format = validate_str_output_format(arg[0]);
		if (OUTPUT_FORMAT_INVALID == io_class_params.output_format)
			return FAILURE;

		io_class_params_options[io_class_opt_output_format].priv |=  (1 << io_class_opt_flag_set);
	}

	return 0;
}

/* Check if all required command were set depending on command type */
int io_class_is_missing() {
	int result = 0;
	int mask;
	cli_option* iter = io_class_params_options;

	for (;iter->long_name; iter++) {
		char option_name[MAX_STR_LEN];
		if (iter->flags & CLI_OPTION_DEFAULT_INT) {
			continue;
		}

		command_name_in_brackets(option_name, MAX_STR_LEN, iter->short_name, iter->long_name);

		if (iter->priv & (1 << io_class_opt_flag_set)) {
			/* Option is set, check if this option is allowed */
			mask = (1 << io_class_params.subcmd);
			if (0 == (mask & iter->priv)) {
				cas_printf(LOG_INFO, "Option '%s' is not allowed\n", option_name);
				result = -1;
			}

		} else {
			/* Option is missing, check if it is required for this sub-command*/
			mask = (1 << io_class_params.subcmd) | (1 << io_class_opt_flag_required);
			if (mask == (iter->priv & mask)) {
				cas_printf(LOG_INFO, "Option '%s' is missing\n", option_name);
				result = -1;
			}
		}
	}

	return result;
}

/* Command handler */
int io_class_handle() {
	/* Check if sub-command was specified */
	if (io_class_opt_subcmd_unknown == io_class_params.subcmd) {
		io_class_print_invalid_subcmd();
		return FAILURE;
	}

	/* Check if all required options are set */
	if (io_class_is_missing()) {
		return FAILURE;
	}

	switch (io_class_params.subcmd) {
	case io_class_opt_subcmd_configure:
		return partition_setup(io_class_params.cache_id,
				io_class_params.file);
	case io_class_opt_subcmd_list:
		return partition_list(io_class_params.cache_id,
				io_class_params.output_format);
	}

	return FAILURE;
}

/*******************************************************************************
 * Script Commands
 ******************************************************************************/
enum {
	script_cmd_unknown = -1,

	script_cmd_min_id = 0,

	script_cmd_upgrade = script_cmd_min_id,
	script_cmd_check_cache_device,

	script_cmd_add_core,
	script_cmd_remove_core,

	script_cmd_max_id,

	script_opt_min_id = script_cmd_max_id,

	script_opt_cache_device = script_opt_min_id,
	script_opt_cache_id,
	script_opt_core_id,
	script_opt_core_device,
	script_opt_try_add,
	script_opt_update_path,
	script_opt_detach,
	script_opt_no_flush,

	script_opt_max_id,

	script_opt_flag_set,
};

/*
 * Field .priv in script_cmd_* elements contains id of required options,
 * script_opt_* .priv fields contains id of commands, where they can be used
 */
static cli_option script_params_options[] = {
	[script_cmd_upgrade] = {
		.short_name = 0,
		.long_name = "upgrade-in-flight",
		.args_count = 0,
		.arg = NULL,
		.priv = 0,
		.flags = CLI_COMMAND_HIDDEN,
	},
	[script_cmd_check_cache_device] = {
		.short_name = 0,
		.long_name = "check-cache-device",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_opt_cache_device),
		.flags = CLI_COMMAND_HIDDEN,
	},
	[script_cmd_add_core] = {
		.short_name = 0,
		.long_name = "add-core",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_opt_core_device)
			| (1 << script_opt_cache_id),
		.flags = CLI_COMMAND_HIDDEN,
	},
	[script_cmd_remove_core] = {
		.short_name = 0,
		.long_name = "remove-core",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_opt_cache_id)
			| (1 << script_opt_core_id),
		.flags = CLI_COMMAND_HIDDEN,
	},
	[script_opt_cache_device] = {
		.short_name = 0,
		.long_name = "cache-device",
		.args_count = 1,
		.arg = "DEVICE",
		.priv = (1 << script_cmd_check_cache_device),
		.flags = CLI_OPTION_HIDDEN,
	},
	[script_opt_cache_id] = {
		.short_name = 0,
		.long_name = "cache-id",
		.args_count = 1,
		.arg = "ID",
		.priv = (1 << script_cmd_remove_core)
			| (1 << script_cmd_add_core),
		.flags = (CLI_OPTION_RANGE_INT | CLI_OPTION_HIDDEN),
		.min_value = OCF_CACHE_ID_MIN,
		.max_value = OCF_CACHE_ID_MAX,
	},
	[script_opt_core_id] = {
		.short_name = 0,
		.long_name = "core-id",
		.args_count = 1,
		.arg = "ID",
		.priv = (1 << script_cmd_remove_core)
			| (1 << script_cmd_add_core),
		.flags = (CLI_OPTION_RANGE_INT | CLI_OPTION_HIDDEN),
		.min_value = OCF_CORE_ID_MIN,
		.max_value = OCF_CORE_ID_MAX,
	},
	[script_opt_core_device] = {
		.short_name = 0,
		.long_name = "core-device",
		.args_count = 1,
		.arg = "DEVICE",
		.priv = (1 << script_cmd_add_core),
		.flags = CLI_OPTION_HIDDEN,
	},
	[script_opt_try_add] = {
		.short_name = 0,
		.long_name = "try-add",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_cmd_add_core),
		.flags = CLI_OPTION_HIDDEN,
	},
	[script_opt_update_path] = {
		.short_name = 0,
		.long_name = "update-path",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_cmd_add_core),
		.flags = CLI_OPTION_HIDDEN,
	},
	[script_opt_detach] = {
		.short_name = 0,
		.long_name = "detach",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_cmd_remove_core),
		.flags = CLI_OPTION_HIDDEN,
	},
	[script_opt_no_flush] = {
		.short_name = 0,
		.long_name = "no-flush",
		.args_count = 0,
		.arg = NULL,
		.priv = (1 << script_cmd_remove_core),
		.flags = CLI_OPTION_HIDDEN,
	},

	{0}
};

int script_handle_option(char *opt, const char **arg)
{
	int id;
	if (script_cmd_unknown == command_args_values.script_subcmd) {
		for (id = script_cmd_min_id; id < script_cmd_max_id; id++) {
			if (!strcmp(opt, script_params_options[id].long_name)) {
				command_args_values.script_subcmd = id;
				return SUCCESS;
			}
		}
		return FAILURE;
	}

	for (id = script_opt_min_id; id < script_opt_max_id; id++) {
		if (!strcmp(opt, script_params_options[id].long_name)) {
			if (command_handle_option(opt, arg) == FAILURE)
				return FAILURE;

			script_params_options[id].priv |= (1 << script_opt_flag_set);

			return SUCCESS;
		}
	}

	return FAILURE;
}

int is_option_allowed(int option_id) {
	cli_option option = script_params_options[option_id];
	int commands_compatible_with_option = option.priv;
	int selected_command = command_args_values.script_subcmd;
	int command_flag = 1 << selected_command;
	int option_is_allowed = command_flag & commands_compatible_with_option;

	return option_is_allowed;
}

int is_option_required(int option_id) {
	int option_flag = (1 << option_id);
	int selected_command = command_args_values.script_subcmd;
	int command_required_options = script_params_options[selected_command].priv;
	int option_is_required = command_required_options & option_flag;

	return option_is_required;
}

int script_command_is_valid() {
	int result = SUCCESS;
	int option_id;
	cli_option* option = &script_params_options[script_opt_min_id];

	for (option_id = script_opt_min_id; option_id < script_opt_max_id; option++, option_id++) {
		char option_name[MAX_STR_LEN];
		int option_is_set = option->priv & (1 << script_opt_flag_set);
		int option_has_default_value = option->flags & CLI_OPTION_DEFAULT_INT;

		if (option_has_default_value)
			continue;

		command_name_in_brackets(option_name, MAX_STR_LEN, option->short_name, option->long_name);

		if (option_is_set) {
			if (!is_option_allowed(option_id)) {
				cas_printf(LOG_INFO, "Option '%s' is not allowed\n", option_name);
				result = FAILURE;
			}
		} else {
			if (is_option_required(option_id)) {
				cas_printf(LOG_INFO, "Option '%s' is missing\n", option_name);
				result = FAILURE;
			}
		}
	}

	return result;
}

int script_handle() {
	if (script_cmd_unknown == command_args_values.script_subcmd) {
		cas_printf(LOG_ERR, "Invalid or missing first sub-command parameter\n");
		return FAILURE;
	}

	if (script_command_is_valid() == FAILURE) {
		return FAILURE;
	}

	switch (command_args_values.script_subcmd) {
	case script_cmd_check_cache_device:
		return check_cache_device(command_args_values.cache_device);
	case script_cmd_upgrade:
		return upgrade_start();
	case script_cmd_add_core:
		return add_core(
			command_args_values.cache_id,
			command_args_values.core_id,
			command_args_values.core_device,
			command_args_values.try_add,
			command_args_values.update_path
			);
	case script_cmd_remove_core:
		return remove_core(
			command_args_values.cache_id,
			command_args_values.core_id,
			command_args_values.detach,
			command_args_values.no_flush
			);
	}

	return FAILURE;
}

/*******************************************************************************
 * NVMe Commands
 ******************************************************************************/

enum {
	nvme_opt_subcmd_format = 0,

	nvme_opt_device,
	nvme_opt_force,

	nvme_opt_flag_required,
	nvme_opt_flag_set,

	nvme_opt_subcmd_unknown,
};

/* NVMe command options */
static cli_option nvme_options[] = {
	[nvme_opt_subcmd_format] = {
		.short_name = 'F',
		.long_name = "format",
		.desc = "Change NVMe metadata mode {normal|atomic} WARNING: Reboot required!",
		.args_count = 1,
		.arg = "MODE",
		.flags = CLI_OPTION_REQUIRED,
	},
	[nvme_opt_device] = {
		.short_name = 'd',
		.long_name = "device",
		.desc = "NVMe device to be formatted",
		.args_count = 1,
		.arg = "DEVICE",
		.flags = CLI_OPTION_REQUIRED,
	},
	[nvme_opt_force] = {
		.short_name = 'f',
		.long_name = "force",
		.desc = "Force NVMe format",
		.args_count = 0,
		.arg = NULL,
		.flags = CLI_OPTION_OPTIONAL_ARG,
	},
	{0}
};


struct {
	const char *device;
	int metadata_mode;
	int force;
} static nvme_params = {
	.device = "",
	.metadata_mode = 0,
	.force = 0,
};


/* Parser of option for IO class command */
int nvme_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "device")) {
		nvme_params.device = arg[0];
	} else if (!strcmp(opt, "format")) {
		nvme_params.metadata_mode = validate_str_metadata_mode(arg[0]);

		if (METADATA_MODE_INVALID == nvme_params.metadata_mode)
			return FAILURE;
	} else if (!strcmp(opt, "force")) {
		nvme_params.force = 1;
	} else {
		return FAILURE;
	}

	return 0;
}

static int handle_nvme_format()
{
	struct kcas_capabilites cas_capabilites;
	static const char fsck_cmd[] = "/sbin/fsck -n %s > /dev/null 2>&1";
	static const uint32_t size = MAX_STR_LEN + sizeof(fsck_cmd) + 1;
	char nvme_dev_path[MAX_STR_LEN];
	char buff[size];

	if (get_cas_capabilites(&cas_capabilites)) {
		cas_printf(LOG_ERR, "Can't obtain CAS capabilities\n");
		return FAILURE;
	}

	if (!cas_capabilites.nvme_format) {
		cas_printf(LOG_ERR, "Command is not supported by current kernel\n");
		return FAILURE;
	}

	if (get_dev_path(nvme_params.device, nvme_dev_path,
			sizeof(nvme_dev_path))) {
		cas_printf(LOG_ERR, "Device does not exist\n");
		return FAILURE;
	}

	snprintf(buff, sizeof(buff), fsck_cmd, nvme_dev_path);

	if (!system(buff)) {
		if (nvme_params.force) {
			cas_printf(LOG_INFO, "A filesystem existed on %s. "
				"Data may have been lost\n",
				nvme_params.device);
		} else {
			/* file system on cache device */
			cas_printf(LOG_ERR, "A filesystem exists on %s. "
				"Specify the --force option if you "
				"wish to format the device anyway.\n"
				"Note: this may result in loss of data\n",
				nvme_params.device);
			return FAILURE;
		}
	}

	return nvme_format(nvme_dev_path, nvme_params.metadata_mode,
			nvme_params.force);
}

static cli_option version_options[] = {
	{
		.short_name = 'o',
		.long_name = "output-format",
		.desc = "Output format: {table|csv}",
		.args_count = 1,
		.arg = "FORMAT",
	},
	{0}
};

int version_handle_option(char *opt, const char **arg)
{
	if (!strcmp(opt, "output-format")) {
		command_args_values.output_format = validate_str_output_format(arg[0]);
		if (OUTPUT_FORMAT_INVALID == command_args_values.output_format)
			return FAILURE;
	} else {
		return FAILURE;
	}

	return 0;
}

static int handle_version(void)
{
	char buff[MAX_STR_LEN];

	FILE *intermediate_file[2];
	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		return FAILURE;
	}

	fprintf(intermediate_file[1], TAG(TABLE_HEADER) "Name,Version\n");

	fprintf(intermediate_file[1], TAG(TABLE_ROW) OCF_LOGO " Cache Kernel Module,");
	if (cas_module_version(buff, MAX_STR_LEN)) {
		fprintf(intermediate_file[1], "Not Loaded\n");
	} else {
		fprintf(intermediate_file[1], "%s\n", buff);
	}

	fprintf(intermediate_file[1], TAG(TABLE_ROW) OCF_LOGO " Disk Kernel Module,");
	if (disk_module_version(buff, MAX_STR_LEN)) {
		fprintf(intermediate_file[1], "Not Loaded\n");
	} else {
		fprintf(intermediate_file[1], "%s\n", buff);
	}

	fprintf(intermediate_file[1], TAG(TABLE_ROW) OCF_LOGO " CLI Utility,");
	fprintf(intermediate_file[1], "%s\n", CAS_VERSION);

	int format = TEXT;
	if (OUTPUT_FORMAT_CSV == command_args_values.output_format) {
		format = RAW_CSV;
	}

	fclose(intermediate_file[1]);
	stat_format_output(intermediate_file[0], stdout, format);
	fclose(intermediate_file[0]);

	return SUCCESS;
}

/* Print help for IO class command */
void io_class_help(app *app_values, cli_command *cmd)
{
	int i, flag = 0, all_ops, printed_ops;
	char option_name[MAX_STR_LEN];
	cli_option* iter = &(cmd->options[0]);

	struct kcas_capabilites caps;
	if (get_cas_capabilites(&caps)) {
		memset(&caps, 0, sizeof(caps));
	}


	/* Print usage */
	cas_printf(LOG_INFO, "Usage: %s --%s {", app_values->name, cmd->name);
	print_options_usage(cmd->options, "|", io_class_print_subcmd, 0);
	cas_printf(LOG_INFO, "}\n\n");

	print_command_header(app_values, cmd);

	for (;iter->long_name; iter++, flag++) {
		if (0 == (iter->flags & CLI_OPTION_DEFAULT_INT)) {
			continue;
		}

		cas_printf(LOG_INFO, "\n");

		cas_printf(LOG_INFO, "%s:\n", iter->desc);

		cas_printf(LOG_INFO, "Usage: %s --%s --%s ", app_values->name,
				cmd->name, iter->long_name);

		all_ops = printed_ops = 0;
		for (i = 0; cmd->options[i].long_name != NULL; i++) {
			if (0 == cmd->options[i].priv) {
				continue;
			}

			if (1 == io_class_print_param(&cmd->options[i], (1 << flag))) {
				all_ops++;
			} else {
				continue;
			}

			if (1 == io_class_print_param(&cmd->options[i], (1 << io_class_opt_flag_required))) {
				printed_ops++;
			}
		}

		print_options_usage(cmd->options, " ", io_class_print_param,
				(1 << flag) | (1 << io_class_opt_flag_required));

		if (all_ops != printed_ops) {
			cas_printf(LOG_INFO, " [option...]");
		}
		command_name_in_brackets(option_name, MAX_STR_LEN, iter->short_name, iter->long_name);
		cas_printf(LOG_INFO, "\nOptions that are valid with %s are:\n", option_name);

		print_list_options(cmd->options, (1 << flag), io_class_print_param);

		cas_printf(LOG_INFO, "\n");
	}
}

static int handle_help();

static cli_command cas_commands[] = {
		{
			.name = "start-cache",
			.short_name = 'S',
			.desc = "Start new cache instance or load using metadata",
			.long_desc = NULL,
			.options = start_options,
			.command_handle_opts = start_cache_command_handle_option,
			.handle = handle_start,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "stop-cache",
			.short_name = 'T',
			.desc = "Stop cache instance",
			.long_desc = NULL,
			.options = stop_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_stop,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "set-param",
			.short_name = 'X',
			.desc = "Set various runtime parameters",
			.long_desc = "Set various runtime parameters",
			.namespace = &set_param_namespace,
			.namespace_handle_opts = set_param_namespace_handle_option,
			.handle = handle_set_param,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "get-param",
			.short_name = 'G',
			.desc = "Get various runtime parameters",
			.long_desc = "Get various runtime parameters",
			.namespace = &get_param_namespace,
			.namespace_handle_opts = get_param_namespace_handle_option,
			.handle = handle_get_param,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "set-cache-mode",
			.short_name = 'Q',
			.desc = "Set cache mode",
			.long_desc = "Set cache mode",
			.options = set_state_cache_mode_options,
			.command_handle_opts = set_cache_mode_command_handle_option,
			.handle = handle_set_cache_mode,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "add-core",
			.short_name = 'A',
			.desc = "Add core device to cache instance",
			.long_desc = NULL,
			.options = add_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_add,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "remove-core",
			.short_name = 'R',
			.desc = "Remove core device from cache instance",
			.long_desc = NULL,
			.options = remove_options,
			.command_handle_opts = remove_core_command_handle_option,
			.handle = handle_remove,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "remove-detached",
			.desc = "Remove core device from core pool",
			.long_desc = NULL,
			.options = core_pool_remove_options,
			.command_handle_opts = core_pool_remove_command_handle_option,
			.handle = handle_core_pool_remove,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "list-caches",
			.short_name = 'L',
			.desc = "List all cache instances and core devices",
			.long_desc = NULL,
			.options = list_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_list,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "stats",
			.short_name = 'P',
			.desc = "Print statistics for cache instance",
			.long_desc = NULL,
			.options = stats_options,
			.command_handle_opts = stats_command_handle_option,
			.handle = handle_stats,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "reset-counters",
			.short_name = 'Z',
			.desc = "Reset cache statistics for core device within cache instance",
			.long_desc = NULL,
			.options = reset_counters_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_reset_counters,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "flush-cache",
			.short_name = 'F',
			.desc = "Flush all dirty data from the caching device to core devices",
			.long_desc = NULL,
			.options = flush_cache_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_flush_cache,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "flush-core",
			.short_name = 'E',
			.desc = "Flush dirty data of a given core from the caching device to this core device",
			.long_desc = NULL,
			.options = flush_core_options,
			.command_handle_opts = command_handle_option,
			.handle = handle_flush_core,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "io-class",
			.short_name = 'C',
			.desc = "Manage IO classes",
			.long_desc = NULL,
			.options = io_class_params_options,
			.command_handle_opts = io_class_handle_option,
			.handle = io_class_handle,
			.flags = CLI_SU_REQUIRED,
			.help = io_class_help,
		},
		{
			.name = "nvme",
			.short_name = 'N',
			.desc = "Manage NVMe namespace",
			.long_desc = NULL,
			.options = nvme_options,
			.command_handle_opts = nvme_handle_option,
			.handle = handle_nvme_format,
			.flags = CLI_SU_REQUIRED,
			.help = NULL,
		},
		{
			.name = "version",
			.short_name = 'V',
			.desc = "Print " OCF_LOGO " version",
			.long_desc = NULL,
			.options = version_options,
			.command_handle_opts = version_handle_option,
			.handle = handle_version,
			.flags = 0,
			.help = NULL
		},
		{
			.name = "help",
			.short_name = 'H',
			.desc = "Print help",
			.long_desc = NULL,
			.options = NULL,
			.command_handle_opts = NULL,
			.flags = 0,
			.handle = handle_help,
			.help = NULL
		},
		{
			.name = "script",
			.options = script_params_options,
			.command_handle_opts = script_handle_option,
			.flags = (CLI_COMMAND_HIDDEN | CLI_SU_REQUIRED),
			.handle = script_handle,
		},
		{0},
};

#define MAN_PAGE "casadm"
#define HELP_FOOTER ""

static int handle_help()
{
	app app_values;
	app_values.name = MAN_PAGE;
	app_values.info = "<command> [option...]";
	app_values.title = HELP_HEADER;
	app_values.doc = HELP_FOOTER;
	app_values.man = MAN_PAGE;
	app_values.block = 0;

	print_help(&app_values, cas_commands);
	return 0;
}

int main(int argc, const char *argv[])
{
	int blocked = 0;
	app app_values;

	set_default_sig_handler();
	set_safe_lib_constraint_handler();

	app_values.name = argv[0];
	app_values.info = "<command> [option...]";
	app_values.title = HELP_HEADER;
	app_values.doc = HELP_FOOTER;
	app_values.man = MAN_PAGE;
	app_values.block = blocked;

	return args_parse(&app_values, cas_commands, argc, argv);
}
