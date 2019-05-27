/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/
#ifndef __LAYER_CACHE_MANAGEMENT_H__
#define __LAYER_CACHE_MANAGEMENT_H__

#define CAS_BLK_DEV_REQ_TYPE_BIO 1
#define CAS_BLK_DEV_REQ_TYPE_REQ 3

struct atomic_dev_params;

int cache_mng_set_cleaning_policy(ocf_cache_id_t cache_id, uint32_t type);

int cache_mng_get_cleaning_policy(ocf_cache_id_t cache_id, uint32_t *type);

int cache_mng_set_cleaning_param(ocf_cache_id_t cache_id, ocf_cleaning_t type,
                uint32_t param_id, uint32_t param_value);

int cache_mng_get_cleaning_param(ocf_cache_id_t cache_id, ocf_cleaning_t type,
                uint32_t param_id, uint32_t *param_value);

int cache_mng_add_core_to_cache(struct ocf_mngt_core_config *cfg,
		ocf_cache_id_t cache_id, struct kcas_insert_core *cmd_info);

int cache_mng_remove_core_from_cache(struct kcas_remove_core *cmd);

int cache_mng_reset_stats(ocf_cache_id_t cache_id,
		ocf_core_id_t core_id);

int cache_mng_set_partitions(struct kcas_io_classes *cfg);

int cache_mng_exit_instance(ocf_cache_id_t id, int flush);

int cache_mng_prepare_cache_cfg(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct atomic_dev_params *atomic_params,
		struct kcas_start_cache *cmd);

int cache_mng_core_pool_get_paths(struct kcas_core_pool_path *cmd_info);

int cache_mng_core_pool_remove(struct kcas_core_pool_remove *cmd_info);

int cache_mng_cache_check_device(struct kcas_cache_check_device *cmd_info);

int cache_mng_prepare_core_cfg(struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info);

int cache_mng_init_instance(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_device_config *device_cfg,
		struct kcas_start_cache *cmd);

int cache_mng_set_seq_cutoff_threshold(ocf_cache_id_t id, ocf_core_id_t core_id,
		uint32_t thresh);

int cache_mng_set_seq_cutoff_policy(ocf_cache_id_t id, ocf_core_id_t core_id,
		ocf_seq_cutoff_policy policy);

int cache_mng_get_seq_cutoff_threshold(ocf_cache_id_t id, ocf_core_id_t core_id,
		uint32_t *thresh);

int cache_mng_get_seq_cutoff_policy(ocf_cache_id_t id, ocf_core_id_t core_id,
		ocf_seq_cutoff_policy *policy);

int cache_mng_set_cache_mode(ocf_cache_id_t id, ocf_cache_mode_t mode,
		uint8_t flush);

int cache_mng_flush_object(ocf_cache_id_t cache_id, ocf_core_id_t core_id);

int cache_mng_flush_device(ocf_cache_id_t id);

ocf_cache_line_t cache_mng_lookup(ocf_cache_t cache,
		ocf_core_id_t core_id, uint64_t core_cacheline);

int cache_mng_list_caches(struct kcas_cache_list *list);

int cache_mng_interrupt_flushing(ocf_cache_id_t id);

int cache_mng_get_info(struct kcas_cache_info *info);

int cache_mng_get_io_class_info(struct kcas_io_class *part);

int cache_mng_get_core_info(struct kcas_core_info *info);

void cache_mng_wait_for_rq_finish(ocf_cache_t cache);

int cache_mng_set_core_params(struct kcas_set_core_param *info);

int cache_mng_get_core_params(struct kcas_get_core_param *info);

int cache_mng_set_cache_params(struct kcas_set_cache_param *info);

int cache_mng_get_cache_params(struct kcas_get_cache_param *info);

#endif
