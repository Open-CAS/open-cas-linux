/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#ifndef __LAYER_CACHE_MANAGEMENT_H__
#define __LAYER_CACHE_MANAGEMENT_H__

#define CAS_BLK_DEV_REQ_TYPE_BIO 1
#define CAS_BLK_DEV_REQ_TYPE_REQ 3

int cache_mngt_set_cleaning_policy(ocf_cache_t cache, uint32_t type);

int cache_mngt_get_cleaning_policy(ocf_cache_t cache, uint32_t *type);

int cache_mngt_set_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
                uint32_t param_id, uint32_t param_value);

int cache_mngt_get_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
                uint32_t param_id, uint32_t *param_value);

int cache_mngt_set_promotion_policy(ocf_cache_t cache, uint32_t type);

int cache_mngt_get_promotion_policy(ocf_cache_t cache, uint32_t *type);

int cache_mngt_set_promotion_param(ocf_cache_t cache, ocf_promotion_t type,
		uint32_t param_id, uint32_t param_value);

int cache_mngt_get_promotion_param(ocf_cache_t cache, ocf_promotion_t type,
		uint32_t param_id, uint32_t *param_value);

int cache_mngt_add_core_to_cache(const char *cache_name, size_t name_len,
		struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info);

int cache_mngt_remove_core_from_cache(struct kcas_remove_core *cmd);

int cache_mngt_remove_inactive_core(struct kcas_remove_inactive *cmd);

int cache_mngt_reset_stats(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len);

int cache_mngt_set_partitions(const char *cache_name, size_t name_len,
		struct kcas_io_classes *cfg);

int cache_mngt_exit_instance(const char *cache_name, size_t name_len,
			int flush);

int cache_mngt_create_cache_cfg(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd);

int cache_mngt_core_pool_get_paths(struct kcas_core_pool_path *cmd_info);

int cache_mngt_core_pool_remove(struct kcas_core_pool_remove *cmd_info);

int cache_mngt_cache_check_device(struct kcas_cache_check_device *cmd_info);

int cache_mngt_prepare_core_cfg(struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info);

int cache_mngt_init_instance(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd);

int cache_mngt_set_seq_cutoff_threshold(ocf_cache_t cache, ocf_core_t core,
		uint32_t thresh);

int cache_mngt_set_seq_cutoff_policy(ocf_cache_t cache, ocf_core_t core,
		ocf_seq_cutoff_policy policy);

int cache_mngt_get_seq_cutoff_threshold(ocf_core_t core, uint32_t *thresh);

int cache_mngt_get_seq_cutoff_policy(ocf_core_t core,
		ocf_seq_cutoff_policy *policy);

int cache_mngt_set_cache_mode(const char *cache_name, size_t name_len,
			ocf_cache_mode_t mode, uint8_t flush);

int cache_mngt_purge_object(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len);

int cache_mngt_flush_object(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len);

int cache_mngt_flush_device(const char *cache_name, size_t name_len);

int cache_mngt_purge_device(const char *cache_name, size_t name_len);

int cache_mngt_list_caches(struct kcas_cache_list *list);

int cache_mngt_interrupt_flushing(const char *cache_name, size_t name_len);

int cache_mngt_get_stats(struct kcas_get_stats *stats);

int cache_mngt_get_info(struct kcas_cache_info *info);

int cache_mngt_get_io_class_info(struct kcas_io_class *part);

int cache_mngt_get_core_info(struct kcas_core_info *info);

void cache_mngt_wait_for_rq_finish(ocf_cache_t cache);

int cache_mngt_set_core_params(struct kcas_set_core_param *info);

int cache_mngt_get_core_params(struct kcas_get_core_param *info);

int cache_mngt_set_cache_params(struct kcas_set_cache_param *info);

int cache_mngt_get_cache_params(struct kcas_get_cache_param *info);

int cache_mngt_standby_detach(struct kcas_standby_detach *cmd);

int cache_mngt_create_cache_standby_activate_cfg(
		struct ocf_mngt_cache_standby_activate_config *cfg,
		struct kcas_standby_activate *cmd);

int cache_mngt_activate(struct ocf_mngt_cache_standby_activate_config *cfg,
		struct kcas_standby_activate *cmd);

#endif
