/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"


struct {
	int cas_error;
	int std_error;
} static cas_error_code_map[] = {
	/* OCF error mappings*/
	{ OCF_ERR_INVAL,			EINVAL	},
	{ OCF_ERR_INVAL_VOLUME_TYPE,		EINVAL	},
	{ OCF_ERR_INTR,				EINTR	},
	{ OCF_ERR_UNKNOWN,			EINVAL	},
	{ OCF_ERR_TOO_MANY_CACHES,		ENOSPC	},
	{ OCF_ERR_NO_MEM,			ENOMEM	},
	{ OCF_ERR_NO_FREE_RAM,			ENOMEM	},
	{ OCF_ERR_START_CACHE_FAIL,		EFAULT	},
	{ OCF_ERR_CACHE_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_CACHE_EXIST,			EEXIST	},
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
	{ OCF_ERR_AGAIN,			EAGAIN  },
	{ OCF_ERR_NOT_SUPP,			ENOTSUP },
	{ OCF_ERR_METADATA_VER,			EBADF	},
	{ OCF_ERR_NO_METADATA,			ENODATA	},

	/* CAS kernel error mappings*/
	{ KCAS_ERR_ROOT,			EPERM	},
	{ KCAS_ERR_SYSTEM,			EINVAL	},
	{ KCAS_ERR_BAD_RANGE,			ERANGE	},
	{ KCAS_ERR_DEV_SPACE,			ENOSPC	},
	{ KCAS_ERR_INV_IOCTL,			EINVAL	},
	{ KCAS_ERR_DEV_PENDING,			EBUSY	},
	{ KCAS_ERR_DIRTY_EXISTS_NVME,		EFAULT	},
	{ KCAS_ERR_FILE_EXISTS,			EEXIST	},
	{ KCAS_ERR_IN_UPGRADE,			EFAULT	},
	{ KCAS_ERR_UNALIGNED,			EINVAL	},
	{ KCAS_ERR_NO_STORED_CONF,		EINTR	},
	{ KCAS_ERR_ROLLBACK,			EFAULT	},
	{ KCAS_ERR_NOT_NVME,			ENODEV	},
	{ KCAS_ERR_FORMAT_FAILED,		EFAULT	},
	{ KCAS_ERR_NVME_BAD_FORMAT,		EINVAL	},
	{ KCAS_ERR_CONTAINS_PART,		EINVAL	},
	{ KCAS_ERR_A_PART,			EINVAL	},
	{ KCAS_ERR_REMOVED_DIRTY,		EIO	},
	{ KCAS_ERR_STOPPED_DIRTY,		EIO	},
};

/*******************************************/
/* Helper which change cas-specific error  */
/* codes to kernel generic error codes     */
/*******************************************/
static inline int map_cas_err_to_generic(int cas_error_code)
{
	int i;

	if (cas_error_code == 0)
		return 0; /* No Error */

	cas_error_code = abs(cas_error_code);

	for (i = 0; i < ARRAY_SIZE(cas_error_code_map); i++) {
		if (cas_error_code_map[i].cas_error == cas_error_code)
			return -cas_error_code_map[i].std_error;
	}

	return -cas_error_code;
}
