/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"


struct cas_error_map_entry {
	int cas_err;
	int errno;
};

static struct cas_error_map_entry cas_ocf_error_map[] = {
	/* OCF error mappings*/
	{ OCF_ERR_INVAL,			EINVAL	},
	{ OCF_ERR_AGAIN,			EAGAIN  },
	{ OCF_ERR_INTR,				EINTR	},
	{ OCF_ERR_NOT_SUPP,			ENOTSUP },
	{ OCF_ERR_NO_MEM,			ENOMEM	},
	{ OCF_ERR_NO_LOCK,			EFAULT	},
	{ OCF_ERR_METADATA_VER,			EBADF	},
	{ OCF_ERR_NO_METADATA,			ENODATA	},
	{ OCF_ERR_METADATA_FOUND,		EEXIST	},
	{ OCF_ERR_INVAL_VOLUME_TYPE,		EINVAL	},
	{ OCF_ERR_UNKNOWN,			EINVAL	},
	{ OCF_ERR_TOO_MANY_CACHES,		ENOSPC	},
	{ OCF_ERR_NO_FREE_RAM,			ENOMEM	},
	{ OCF_ERR_START_CACHE_FAIL,		EFAULT	},
	{ OCF_ERR_CACHE_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_CORE_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_CACHE_EXIST,			EEXIST	},
	{ OCF_ERR_CORE_EXIST,			EEXIST	},
	{ OCF_ERR_TOO_MANY_CORES,		ENOSPC	},
	{ OCF_ERR_CORE_NOT_AVAIL,		ENAVAIL	},
	{ OCF_ERR_NOT_OPEN_EXC,			EBUSY	},
	{ OCF_ERR_CACHE_NOT_AVAIL,		ENAVAIL	},
	{ OCF_ERR_IO_CLASS_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_IO,				EIO	},
	{ OCF_ERR_WRITE_CACHE,			EIO	},
	{ OCF_ERR_WRITE_CORE,			EIO	},
	{ OCF_ERR_DIRTY_SHUTDOWN,		EFAULT	},
	{ OCF_ERR_DIRTY_EXISTS,			EFAULT	},
	{ OCF_ERR_FLUSHING_INTERRUPTED,		EINTR	},
	{ OCF_ERR_FLUSH_IN_PROGRESS,		EBUSY	},
	{ OCF_ERR_CANNOT_ADD_CORE_TO_POOL,	EFAULT	},
	{ OCF_ERR_CACHE_IN_INCOMPLETE_STATE,	ENODEV	},
	{ OCF_ERR_CORE_IN_INACTIVE_STATE,	ENODEV	},
	{ OCF_ERR_INVALID_CACHE_MODE,		EINVAL	},
	{ OCF_ERR_INVALID_CACHE_LINE_SIZE,	EINVAL	},
	{ OCF_ERR_CACHE_NAME_MISMATCH,		EINVAL	},
	{ OCF_ERR_INVAL_CACHE_DEV,		EINVAL	},
	{ OCF_ERR_CORE_UUID_EXISTS,		EINVAL	},
	{ OCF_ERR_CACHE_LINE_SIZE_MISMATCH,	EINVAL	},
	{ OCF_ERR_CACHE_STANDBY,		EBUSY	},
};

static struct cas_error_map_entry cas_error_map[] = {
	/* CAS kernel error mappings*/
	{ KCAS_ERR_ROOT,			EPERM	},
	{ KCAS_ERR_SYSTEM,			EINVAL	},
	{ KCAS_ERR_BAD_RANGE,			ERANGE	},
	{ KCAS_ERR_DEV_SPACE,			ENOSPC	},
	{ KCAS_ERR_INV_IOCTL,			EINVAL	},
	{ KCAS_ERR_DEV_PENDING,			EBUSY	},
	{ KCAS_ERR_FILE_EXISTS,			EEXIST	},
	{ KCAS_ERR_UNALIGNED,			EINVAL	},
	{ KCAS_ERR_ROLLBACK,			EFAULT	},
	{ KCAS_ERR_NVME_BAD_FORMAT,		EINVAL	},
	{ KCAS_ERR_CONTAINS_PART,		EINVAL	},
	{ KCAS_ERR_A_PART,			EINVAL	},
	{ KCAS_ERR_DETACHED,			EIO	},
	{ KCAS_ERR_STOPPED_DIRTY,		EIO	},
	{ KCAS_ERR_CORE_POOL_NOT_EMPTY,		EEXIST	},
	{ KCAS_ERR_NO_CACHE_ATTACHED,		ENODEV	},
	{ KCAS_ERR_CLS_RULE_INVALID_SYNTAX,	EINVAL	},
	{ KCAS_ERR_CLS_RULE_UNKNOWN_CONDITION,	EINVAL	},
	{ KCAS_ERR_WAITING_INTERRUPTED,		EINTR	},
	{ KCAS_ERR_CORE_IN_ACTIVE_STATE,	ENODEV	},
	{ KCAS_ERR_INACTIVE_CORE_IS_DIRTY,	ENODEV	},
};

/*******************************************/
/* Helper which change cas-specific error  */
/* codes to kernel generic error codes     */
/*******************************************/
static inline int map_cas_err_to_generic(int error_code)
{
	int i;

	if (error_code == 0)
		return 0; /* No Error */

	error_code = abs(error_code);

	if (error_code >= OCF_ERR_MIN && error_code <= OCF_ERR_MAX) {
		for (i = 0; i < ARRAY_SIZE(cas_ocf_error_map); i++) {
			if (cas_ocf_error_map[i].cas_err == error_code)
				return -cas_ocf_error_map[i].errno;
		}
		return -EINVAL;
	}

	if (error_code >= KCAS_ERR_MIN && error_code <= KCAS_ERR_MAX) {
		for (i = 0; i < ARRAY_SIZE(cas_error_map); i++) {
			if (cas_error_map[i].cas_err == error_code)
				return -cas_error_map[i].errno;
		}
		return -EINVAL;
	}

	return -error_code;
}
