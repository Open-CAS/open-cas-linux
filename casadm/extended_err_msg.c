/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include "safeclib/safe_lib.h"
#include <cas_ioctl_codes.h>
#include "extended_err_msg.h"

struct {
	int cas_error;
	const char *msg;
} static cas_error_code_map[] = {

	/* IOC error mappings*/
	{
		OCF_ERR_INVAL,
		"Invalid input parameter"
	},
	{
		OCF_ERR_INVAL_VOLUME_TYPE,
		"Invalid volume type"
	},
	{
		OCF_ERR_INTR,
		"Interrupted by a signal"
	},
	{
		OCF_ERR_UNKNOWN,
		"Unknown error occurred"
	},
	{
		OCF_ERR_TOO_MANY_CACHES,
		"Too many caches"
	},
	{
		OCF_ERR_NO_MEM,
		"Not enough memory to allocate a new cache device"
	},
	{
		OCF_ERR_NO_FREE_RAM,
		"Not enough free RAM for cache metadata to start cache"
	},
	{
		OCF_ERR_START_CACHE_FAIL,
		"Failed to insert cache"
	},
	{
		OCF_ERR_CACHE_NOT_EXIST,
		"Cache ID does not exist"
	},
	{
		OCF_ERR_CORE_NOT_EXIST,
		"Core ID does not exist"
	},
	{
		OCF_ERR_CACHE_EXIST,
		"Cache ID already exists"
	},
	{
		OCF_ERR_TOO_MANY_CORES,
		"Too many core devices in cache"
	},
	{
		OCF_ERR_CORE_EXIST,
		"Core id already used"
	},
	{
		OCF_ERR_CORE_UUID_EXISTS,
		"Device already added as a core"
	},
	{
		OCF_ERR_CORE_NOT_AVAIL,
		"Core device not available"
	},
	{
		OCF_ERR_CACHE_NOT_AVAIL,
		"Cache device not available"
	},
	{
		OCF_ERR_IO_CLASS_NOT_EXIST,
		"No such IO class ID in the cache"
	},
	{	OCF_ERR_IO,
		"I/O error"
	},
	{
		OCF_ERR_WRITE_CACHE,
		"Error while writing to cache device"
	},
	{
		OCF_ERR_WRITE_CORE,
		"Error while writing to core device"
	},
	{
		OCF_ERR_DIRTY_SHUTDOWN,
		"Please use --load option to restore previous cache state "
		"(Warning: data corruption may happen)\nOr initialize your "
		"cache using --force option. Warning: All dirty data will be "
		"lost!\n"
	},
	{
		OCF_ERR_DIRTY_EXISTS,
		"Cache closed with dirty data.\nPlease start cache using "
		"--load or --force option.\n"
	},
	{
		OCF_ERR_FLUSHING_INTERRUPTED,
		"Flushing of core interrupted"
	},
	{
		OCF_ERR_FLUSH_IN_PROGRESS,
		"Another flush operation in progress"
	},
	{
		OCF_ERR_CANNOT_ADD_CORE_TO_POOL,
		"Error occurred during adding core device to core pool"
	},
	{
		OCF_ERR_CACHE_IN_INCOMPLETE_STATE,
		"Cache is in incomplete state - at least one core is inactive"
	},
	{
		OCF_ERR_CORE_IN_INACTIVE_STATE,
		"Core device is in inactive state"
	},
	{
		OCF_ERR_NOT_OPEN_EXC,
		"Cannot open device exclusively"
	},
	{
		OCF_ERR_AGAIN,
		"Try again"
	},
	{
		OCF_ERR_NOT_SUPP,
		"Operation not supported"
	},
	{
		OCF_ERR_METADATA_VER,
		"Metadata version mismatch"
	},
	{
		OCF_ERR_NO_METADATA,
		"No metadata found on device"
	},
	{
		OCF_ERR_METADATA_FOUND,
		"Old metadata found on device.\nPlease load cache metadata using --load"
		" option or use --force to\n discard on-disk metadata and"
		" start fresh cache instance.\n"
	},
	{
		OCF_ERR_SUPERBLOCK_MISMATCH,
		"Metadata on the device doesn't match with metadata in DRAM"
	},
	{
		OCF_ERR_CRC_MISMATCH,
		"Metadata checksum is not correct. Metadata is damaged"
	},
	{
		OCF_ERR_CACHE_NAME_MISMATCH,
		"Cache id specified by user and loaded from metadata are different"
	},
	{
		OCF_ERR_INVAL_CACHE_DEV,
		"Device does not meet requirements. See dmesg for more information"
	},
	{
		OCF_ERR_NO_LOCK,
		"Failed to lock cache for management operation."
	},
	{
		OCF_ERR_CACHE_LINE_SIZE_MISMATCH,
		"Cache line size mismatch"
	},
	{
		OCF_ERR_CACHE_STANDBY,
		"The operation is not permited while the cache is in the standby mode"
	},
	{
		OCF_ERR_STANDBY_ATTACHED,
		"Cache device is attached, please detach it first with --standby --detach"
	},
	{
		OCF_ERR_CORE_SIZE_MISMATCH,
		"Core volume size does not match"
		" the size stored in cache metadata"
	},
	{
		OCF_ERR_CORE_NOT_REMOVED,
		"Unable fully remove core due to metadata flush error.\n"
		"Exported object was removed, but core object still exists."
	},

	/* CAS kernel error mappings*/
	{
		KCAS_ERR_ROOT,
		"Must be root"
	},
	{
		KCAS_ERR_SYSTEM,
		"System Error"
	},
	{
		KCAS_ERR_BAD_RANGE,
		"Range parameters are invalid"
	},
	{
		KCAS_ERR_DEV_SPACE,
		"Illegal range, out of device space"
	},
	{
		KCAS_ERR_INV_IOCTL,
		"Invalid ioctl"
	},
	{
		KCAS_ERR_DEV_PENDING,
		"Device opens or mount are pending to this cache"
	},
	{
		KCAS_ERR_FILE_EXISTS,
		"Could not create exported object because file in /dev "
		"directory exists"
	},
	{
		KCAS_ERR_UNALIGNED,
		"Cache device logical sector size is greater than core device "
		"logical sector size.\nConsider changing logical sector size "
		"on current cache device \nor try other device with the same "
		"logical sector size as core device."
	},
	{
		KCAS_ERR_CONTAINS_PART,
		"Device contains partitions.\nIf you want to continue, "
		"please use --force option.\nWarning: all data will be lost!"
	},
	{
		KCAS_ERR_A_PART,
		"Formatting of partition is unsupported."
	},
	{
		KCAS_ERR_DETACHED,
		"Failed to remove core. See dmesg for more information"
	},
	{
		KCAS_ERR_STOPPED_DIRTY,
		"Cache has been stopped with flushing error.\n"
		"Warning: Core devices may contain inconsistent data.\n"
		"To access your data, please start cache with --load option."
	},
	{
		KCAS_ERR_NO_CACHE_ATTACHED,
		"Operation not allowed. Caching device is not attached."
	},
	{
		KCAS_ERR_CORE_POOL_NOT_EMPTY,
		"Operation not allowed. Core pool is not empty."
	},
	{
		KCAS_ERR_CLS_RULE_UNKNOWN_CONDITION,
		"Unexpected classification rule condition"
	},
	{
		KCAS_ERR_CLS_RULE_INVALID_SYNTAX,
		"Invalid classification rule syntax"
	},
	{
		KCAS_ERR_WAITING_INTERRUPTED,
		"Waiting for operation interrupted"
	},
	{
		KCAS_ERR_CORE_IN_ACTIVE_STATE,
		"Core device is in active state"
	},
	{
		KCAS_ERR_INACTIVE_CORE_IS_DIRTY,
		"The cache contains dirty data assigned to the core. If you want to "
		"continue, please use --force option.\nWarning: the data will be lost"
	},
	{
		KCAS_ERR_STANDBY_DETACHED,
		"Cache device is already in standby detached state."
	},
};

const char *cas_strerr(int cas_error_code)
{
	int i;
	int count = sizeof(cas_error_code_map) / sizeof(cas_error_code_map[0]);

	if (cas_error_code == 0)
		return NULL; /* No Error */

	cas_error_code = abs(cas_error_code);

	for (i = 0; i < count; i++) {
		if (cas_error_code_map[i].cas_error == cas_error_code)
			return cas_error_code_map[i].msg;
	}

	return strerror(cas_error_code);
}

