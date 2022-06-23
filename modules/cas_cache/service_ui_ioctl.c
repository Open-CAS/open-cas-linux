/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "utils/cas_err.h"

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
	return map_cas_err_to_generic(ret); \
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

	switch (cmd) {
	case KCAS_IOCTL_START_CACHE: {
		struct kcas_start_cache *cmd_info;
		struct ocf_mngt_cache_config cfg;
		struct ocf_mngt_cache_attach_config attach_cfg;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_create_cache_cfg(&cfg, &attach_cfg, cmd_info);
		if (retval)
			RETURN_CMD_RESULT(cmd_info, arg, retval);

		retval = cache_mngt_init_instance(&cfg, &attach_cfg, cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_STOP_CACHE: {
		struct kcas_stop_cache *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_exit_instance(cache_name, OCF_CACHE_NAME_SIZE,
				cmd_info->flush_data);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_SET_CACHE_STATE: {
		struct kcas_set_cache_state *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_set_cache_mode(cache_name,
				OCF_CACHE_NAME_SIZE, cmd_info->caching_mode,
				cmd_info->flush_data);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_INSERT_CORE: {
		struct kcas_insert_core *cmd_info;
		struct ocf_mngt_core_config cfg;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_prepare_core_cfg(&cfg, cmd_info);
		if (retval)
			RETURN_CMD_RESULT(cmd_info, arg, retval);

		retval = cache_mngt_add_core_to_cache(cache_name,
					OCF_CACHE_NAME_SIZE, &cfg, cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_REMOVE_CORE: {
		struct kcas_remove_core *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_remove_core_from_cache(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_REMOVE_INACTIVE: {
		struct kcas_remove_inactive *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_remove_inactive_core(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_RESET_STATS: {
		struct kcas_reset_stats *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];
		char core_name[OCF_CORE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		if (cmd_info->core_id != OCF_CORE_ID_INVALID)
			core_name_from_id(core_name, cmd_info->core_id);

		retval = cache_mngt_reset_stats(cache_name, OCF_CACHE_NAME_SIZE,
				cmd_info->core_id != OCF_CORE_ID_INVALID ?
						core_name : NULL,
				cmd_info->core_id != OCF_CORE_ID_INVALID ?
						OCF_CORE_NAME_SIZE : 0);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_PURGE_CACHE: {
		struct kcas_flush_cache *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_purge_device(cache_name, OCF_CACHE_NAME_SIZE);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_FLUSH_CACHE: {
		struct kcas_flush_cache *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_flush_device(cache_name, OCF_CACHE_NAME_SIZE);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_INTERRUPT_FLUSHING: {
		struct kcas_interrupt_flushing *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_interrupt_flushing(cache_name,
						OCF_CACHE_NAME_SIZE);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_PURGE_CORE: {
		struct kcas_flush_core *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];
		char core_name[OCF_CORE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		core_name_from_id(core_name, cmd_info->core_id);

		retval = cache_mngt_purge_object(cache_name, OCF_CACHE_NAME_SIZE,
						core_name, OCF_CORE_NAME_SIZE);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_FLUSH_CORE: {
		struct kcas_flush_core *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];
		char core_name[OCF_CORE_NAME_SIZE];

		GET_CMD_INFO(cmd_info, arg);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		core_name_from_id(core_name, cmd_info->core_id);

		retval = cache_mngt_flush_object(cache_name, OCF_CACHE_NAME_SIZE,
						core_name, OCF_CORE_NAME_SIZE);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_GET_STATS: {
		struct kcas_get_stats *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_stats(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_CACHE_INFO: {
		struct kcas_cache_info *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_CORE_INFO: {
		struct kcas_core_info *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_core_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}

	case KCAS_IOCTL_PARTITION_INFO: {
		struct kcas_io_class *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_io_class_info(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);

	}

	case KCAS_IOCTL_PARTITION_SET: {
		struct kcas_io_classes *cmd_info;
		char cache_name[OCF_CACHE_NAME_SIZE];

		/* copy entire memory from user, including array of
		 * ocf_io_class_info structs past the end of kcas_io_classes */
		_GET_CMD_INFO(cmd_info, arg, KCAS_IO_CLASSES_SIZE);

		cache_name_from_id(cache_name, cmd_info->cache_id);

		retval = cache_mngt_set_partitions(cache_name,
						OCF_CACHE_NAME_SIZE, cmd_info);

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

		retval = cache_mngt_list_caches(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval > 0 ? 0 : retval);
	}

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

		retval = cache_mngt_core_pool_get_paths(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_CORE_POOL_REMOVE: {
		struct kcas_core_pool_remove *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_core_pool_remove(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_CACHE_CHECK_DEVICE: {
		struct kcas_cache_check_device *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_cache_check_device(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_SET_CORE_PARAM: {
		struct kcas_set_core_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_set_core_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_GET_CORE_PARAM: {
		struct kcas_get_core_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_core_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_SET_CACHE_PARAM: {
		struct kcas_set_cache_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_set_cache_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_GET_CACHE_PARAM: {
		struct kcas_get_cache_param *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_get_cache_params(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_STANDBY_DETACH: {
		struct kcas_standby_detach *cmd_info;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_standby_detach(cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	case KCAS_IOCTL_STANDBY_ACTIVATE: {
		struct kcas_standby_activate *cmd_info;
		struct ocf_mngt_cache_standby_activate_config cfg;

		GET_CMD_INFO(cmd_info, arg);

		retval = cache_mngt_create_cache_standby_activate_cfg(&cfg,
				cmd_info);
		if (retval)
			RETURN_CMD_RESULT(cmd_info, arg, retval);

		retval = cache_mngt_activate(&cfg, cmd_info);

		RETURN_CMD_RESULT(cmd_info, arg, retval);
	}
	default:
		return -EINVAL;
	}
}
