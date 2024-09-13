#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas.casadm_parser import *
from api.cas.core import Core
from api.cas.dmesg import get_metadata_size_on_device
from api.cas.statistics import CacheStats, CacheIoClassStats
from test_utils.os_utils import *
from test_utils.output import Output


class Cache:
    def __init__(self, device: Device, cache_id: int = None) -> None:
        self.cache_device = device
        self.cache_id = cache_id if cache_id else self.__get_cache_id()
        self.__cache_line_size = None
        self.metadata_size_on_disk = self.get_metadata_size_on_disk()

    def __get_cache_id(self) -> int:
        device_path = self.__get_cache_device_path()

        caches_dict = get_cas_devices_dict()["caches"]

        for cache in caches_dict.values():
            if cache["device_path"] == device_path:
                return int(cache["id"])

        raise Exception(f"There is no cache started on {device_path}")

    def __get_cache_device_path(self) -> str:
        return self.cache_device.path if self.cache_device is not None else "-"

    def get_core_devices(self) -> list:
        return get_cores(self.cache_id)

    def get_cache_line_size(self) -> CacheLineSize:
        if self.__cache_line_size is None:
            stats = self.get_statistics()
            stats_line_size = stats.config_stats.cache_line_size
            self.__cache_line_size = CacheLineSize(stats_line_size)
        return self.__cache_line_size

    def get_cleaning_policy(self) -> CleaningPolicy:
        stats = self.get_statistics()
        cp = stats.config_stats.cleaning_policy
        return CleaningPolicy[cp]

    def get_metadata_size_in_ram(self) -> Size:
        stats = self.get_statistics()
        return stats.config_stats.metadata_memory_footprint

    def get_metadata_size_on_disk(self) -> Size:
        return get_metadata_size_on_device(cache_id=self.cache_id)

    def get_occupancy(self):
        return self.get_statistics().usage_stats.occupancy

    def get_status(self) -> CacheStatus:
        status = (
            self.get_statistics(stat_filter=[StatsFilter.conf])
            .config_stats.status.replace(" ", "_")
            .lower()
        )
        return CacheStatus[status]

    @property
    def size(self) -> Size:
        return self.get_statistics().config_stats.cache_size

    def get_cache_mode(self) -> CacheMode:
        return CacheMode[self.get_statistics().config_stats.write_policy.upper()]

    def get_dirty_blocks(self) -> Size:
        return self.get_statistics().usage_stats.dirty

    def get_dirty_for(self) -> timedelta:
        return self.get_statistics().config_stats.dirty_for

    def get_clean_blocks(self) -> Size:
        return self.get_statistics().usage_stats.clean

    def get_flush_parameters_alru(self) -> FlushParametersAlru:
        return get_flush_parameters_alru(self.cache_id)

    def get_flush_parameters_acp(self) -> FlushParametersAcp:
        return get_flush_parameters_acp(self.cache_id)

    # Casadm methods:

    def get_statistics(
        self,
        stat_filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ) -> CacheStats:
        return CacheStats(
            cache_id=self.cache_id,
            filter=stat_filter,
            percentage_val=percentage_val,
        )

    def get_io_class_statistics(
        self,
        io_class_id: int = None,
        stat_filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ) -> CacheIoClassStats:
        return CacheIoClassStats(
            cache_id=self.cache_id,
            filter=stat_filter,
            io_class_id=io_class_id,
            percentage_val=percentage_val,
        )

    def flush_cache(self) -> Output:
        output = casadm.flush_cache(cache_id=self.cache_id)
        sync()
        return output

    def purge_cache(self) -> Output:
        output = casadm.purge_cache(cache_id=self.cache_id)
        sync()
        return output

    def stop(self, no_data_flush: bool = False) -> Output:
        return casadm.stop_cache(self.cache_id, no_data_flush)

    def add_core(self, core_dev, core_id: int = None) -> Core:
        return casadm.add_core(self, core_dev, core_id)

    def remove_core(self, core_id: int, force: bool = False) -> Output:
        return casadm.remove_core(self.cache_id, core_id, force)

    def remove_inactive_core(self, core_id: int, force: bool = False) -> Output:
        return casadm.remove_inactive(self.cache_id, core_id, force)

    def reset_counters(self) -> Output:
        return casadm.reset_counters(self.cache_id)

    def set_cache_mode(self, cache_mode: CacheMode, flush=None) -> Output:
        return casadm.set_cache_mode(cache_mode, self.cache_id, flush)

    def load_io_class(self, file_path: str) -> Output:
        return casadm.load_io_classes(self.cache_id, file_path)

    def list_io_classes(self) -> list:
        return get_io_class_list(self.cache_id)

    def set_seq_cutoff_parameters(self, seq_cutoff_param: SeqCutOffParameters) -> Output:
        return casadm.set_param_cutoff(
            self.cache_id,
            threshold=seq_cutoff_param.threshold,
            policy=seq_cutoff_param.policy,
            promotion_count=seq_cutoff_param.promotion_count,
        )

    def set_seq_cutoff_threshold(self, threshold: Size) -> Output:
        return casadm.set_param_cutoff(self.cache_id, threshold=threshold, policy=None)

    def set_seq_cutoff_policy(self, policy: SeqCutOffPolicy) -> Output:
        return casadm.set_param_cutoff(self.cache_id, threshold=None, policy=policy)

    def set_cleaning_policy(self, cleaning_policy: CleaningPolicy) -> Output:
        return casadm.set_param_cleaning(self.cache_id, cleaning_policy)

    def set_params_acp(self, acp_params: FlushParametersAcp) -> Output:
        return casadm.set_param_cleaning_acp(
            self.cache_id,
            int(acp_params.wake_up_time.total_milliseconds()) if acp_params.wake_up_time else None,
            int(acp_params.flush_max_buffers) if acp_params.flush_max_buffers else None,
        )

    def set_params_alru(self, alru_params: FlushParametersAlru) -> Output:
        return casadm.set_param_cleaning_alru(
            self.cache_id,
            (int(alru_params.wake_up_time.total_seconds()) if alru_params.wake_up_time else None),
            (
                int(alru_params.staleness_time.total_seconds())
                if alru_params.staleness_time
                else None
            ),
            (alru_params.flush_max_buffers if alru_params.flush_max_buffers else None),
            (
                int(alru_params.activity_threshold.total_milliseconds())
                if alru_params.activity_threshold
                else None
            ),
        )

    def set_promotion_policy(self, policy: PromotionPolicy) -> Output:
        return casadm.set_param_promotion(self.cache_id, policy)

    def set_params_nhit(self, promotion_params_nhit: PromotionParametersNhit) -> Output:
        return casadm.set_param_promotion_nhit(
            self.cache_id,
            threshold=promotion_params_nhit.threshold.get_value(),
            trigger=promotion_params_nhit.trigger
        )

    def get_cache_config(self) -> CacheConfig:
        return CacheConfig(
            self.get_cache_line_size(),
            self.get_cache_mode(),
            self.get_cleaning_policy(),
        )

    def standby_detach(self, shortcut: bool = False) -> Output:
        return casadm.standby_detach_cache(cache_id=self.cache_id, shortcut=shortcut)

    def standby_activate(self, device, shortcut: bool = False) -> Output:
        return casadm.standby_activate_cache(
            cache_id=self.cache_id, cache_dev=device, shortcut=shortcut
        )

    def has_volatile_metadata(self) -> bool:
        return self.get_metadata_size_on_disk() == Size.zero()
