/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"

struct {
	int cas_error;
	int std_error;
} static cas_error_code_map[] = {
	/* IOC error mappings*/
	{ OCF_ERR_INVAL,			EINVAL	},
	{ OCF_ERR_INVAL_VOLUME_TYPE,		EINVAL	},
	{ OCF_ERR_INTR,				EINTR	},
	{ OCF_ERR_UNKNOWN,			EINVAL	},
	{ OCF_ERR_TOO_MANY_CACHES,		ENOSPC	},
	{ OCF_ERR_NO_MEM,			ENOMEM	},
	{ OCF_ERR_NO_FREE_RAM,			ENOMEM	},
	{ OCF_ERR_START_CACHE_FAIL,		EFAULT	},
	{ OCF_ERR_CACHE_IN_USE,			EBUSY	},
	{ OCF_ERR_CACHE_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_CACHE_EXIST,			EEXIST	},
	{ OCF_ERR_TOO_MANY_CORES,		ENOSPC	},
	{ OCF_ERR_CORE_NOT_AVAIL,		ENAVAIL	},
	{ OCF_ERR_NOT_OPEN_EXC,			EBUSY	},
	{ OCF_ERR_CACHE_NOT_AVAIL,		ENAVAIL	},
	{ OCF_ERR_IO_CLASS_NOT_EXIST,		ENODEV	},
	{ OCF_ERR_WRITE_CACHE,			EIO	},
	{ OCF_ERR_WRITE_CORE,			EIO	},
	{ OCF_ERR_DIRTY_SHUTDOWN,		EFAULT	},
	{ OCF_ERR_DIRTY_EXISTS,			EFAULT	},
	{ OCF_ERR_FLUSHING_INTERRUPTED,		EINTR	},

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

int map_cas_err_to_generic_code(int cas_error_code)
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

#define _GET_CMD_INFO(cmd_info, arg, size) ({ \
	cmd_info = vmalloc(size); \
	if (!cmd_info) \
		return -ENOMEM; \
	if (copy_from_user(cmd_info, (void __user *)arg, size)) { \
		printk(KERN_ALERT "Cannot copy cmd info from user space\n"); \
		vfree(cmd_info); \
		return -EINVAL; \
	} \
})

#define GET_CMD_INFO(cmd_info, arg) _GET_CMD_INFO(cmd_info, arg, \
		sizeof(*cmd_info))

#define RETURN_CMD_RESULT(cmd_info, arg, result) ({ \
	int ret = result; \
	cmd_info->ext_err_code = abs(result); \
	if (copy_to_user((void __user *)arg, cmd_info, sizeof(*cmd_info))) { \
		printk(KERN_ALERT "Unable to copy response to user\n"); \
		ret = -EFAULT; \
	} \
	vfree(cmd_info); \
	return map_cas_err_to_generic_code(ret); \
})

/* this handles IOctl for /dev/cas */
/*********************************************/
long cas_service_ioctl_ctrl(struct file *filp, unsigned int cmd,
		unsigned long arg)
{
	int retval = 0;

	if (_IOC_TYPE(cmd) != KCAS_IOCTL_MAGIC)
		return -EINVAL;

	if (!capable(CAP_SYS_ADMIN)) {
		/* Must be root to issue ioctls */
		return -EPERM;
	}

	if (cas_upgrade_is_in_upgrade() &&
		cmd != KCAS_IOCTL_CACHE_INFO &&
		cmd != KCAS_IOCTL_LIST_CACHE &&
		cmd != KCAS_IOCTL_GET_CACHE_COUNT &&
		cmd != KCAS_IOCTL_CORE_INFO &&
		cmd != KCAS_IOCTL_PARTITION_STATS &&
		cmd != KCAS_IOCTL_GET_CAPABILITIES) {
		return -EFAULT;
	}

	switch (cmd) {
	case KCAS_IOCTL_START_CACHE: {
		struct kcas_start_cache *cmd_info;
		struct ocf_mngt_cache_config cfg;
		struct ocf_mngt_cache_device_config device_cfg;
		struct atomic_dev_params atomic_params = { 0 };

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_prepare_cache_cfg(&cfg, &device_cfg,
				&atomic_params, cmd_info);
		if (retval)
			RETURN_CMD_RESULT(cmd_info, arg, retval);

		retval = cache_mng_init_instance(&cfg, &device_cfg, cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_STOP_CACHE: {
		struct kcas_stop_cache *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_exit_instance(cmd_info->cache_id,
				cmd_info->flush_data);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_SET_CACHE_STATE: {
		struct kcas_set_cache_state *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_set_cache_mode(cmd_info->cache_id,
				cmd_info->caching_mode, cmd_info->flush_data);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_INSERT_CORE: {
		struct kcas_insert_core *cmd_info;
		struct ocf_mngt_core_config cfg;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_prepare_core_cfg(&cfg, cmd_info);
		if (retval)
			RETURN_CMD_RESULT(cmd_info, arg, retval);

		retval = cache_mng_add_core_to_cache(&cfg, cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_REMOVE_CORE: {
		struct kcas_remove_core *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_remove_core_from_cache(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_RESET_STATS: {
		struct kcas_reset_stats *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_reset_core_stats(cmd_info->cache_id,
				cmd_info->core_id);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_FLUSH_CACHE: {
		struct kcas_flush_cache *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_flush_device(cmd_info->cache_id);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_INTERRUPT_FLUSHING: {
		struct kcas_interrupt_flushing *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_interrupt_flushing(cmd_info->cache_id);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_FLUSH_CORE: {
		struct kcas_flush_core *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_flush_object(cmd_info->cache_id,
				cmd_info->core_id);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_CACHE_INFO: {
		struct kcas_cache_info *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_get_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_CORE_INFO: {
		struct kcas_core_info *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_get_core_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_PARTITION_STATS: {
		struct kcas_io_class *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_get_io_class_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);

	}

	case KCAS_IOCTL_PARTITION_SET: {
		struct kcas_io_classes *cmd_info;

		/* copy entire memory from user, including array of
		 * ocf_io_class_info structs past the end of kcas_io_classes */
		_GET_CMD_INFO(cmd_info, arg, KCAS_IO_CLASSES_SIZE);

		retval = cache_mng_set_partitions(cmd_info);

		/* return just sizeof(struct kcas_io_classes) bytes of data */
		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_GET_CACHE_COUNT: {
		struct kcas_cache_count *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		cmd_info->cache_count = ocf_mngt_cache_get_count(cas_ctx);

		RETURN_CMD_RESULT(cmd_info, arg, 0);
	}

	case KCAS_IOCTL_LIST_CACHE: {
		struct kcas_cache_list *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_list_caches(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval > 0 ? 0 : retval);
	}

	case KCAS_IOCTL_GET_CAPABILITIES: {
		struct kcas_capabilites *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		memset(cmd_info, 0, sizeof(*cmd_info));
#ifdef CAS_NVME_FULL
		cmd_info->nvme_format = 1;
#endif
		RETURN_CMD_RESULT(cmd_info, arg, 0);
	}

	case KCAS_IOCTL_UPGRADE: {
		struct kcas_upgrade *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cas_upgrade();

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

#if defined(CAS_NVME_FULL)
	case KCAS_IOCTL_NVME_FORMAT: {
		struct kcas_nvme_format *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cas_nvme_format_optimal(
				cmd_info->device_path_name,
				cmd_info->metadata_mode,
				cmd_info->force);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
#endif

	case KCAS_IOCTL_GET_CORE_POOL_COUNT: {
		struct kcas_core_pool_count *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		cmd_info->core_pool_count =
				ocf_mngt_core_pool_get_count(cas_ctx);

		RETURN_CMD_RESULT(cmd_info, arg, 0);
	}

	case KCAS_IOCTL_GET_CORE_POOL_PATHS: {
		struct kcas_core_pool_path *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_core_pool_get_paths(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_CORE_POOL_REMOVE: {
		struct kcas_core_pool_remove *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_core_pool_remove(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_CACHE_CHECK_DEVICE: {
		struct kcas_cache_check_device *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_cache_check_device(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_SET_CORE_PARAM: {
		struct kcas_set_core_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_set_core_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_GET_CORE_PARAM: {
		struct kcas_get_core_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_get_core_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_SET_CACHE_PARAM: {
		struct kcas_set_cache_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_set_cache_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_GET_CACHE_PARAM: {
		struct kcas_get_cache_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mng_get_cache_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	default:
		return -EINVAL;
	}
}
