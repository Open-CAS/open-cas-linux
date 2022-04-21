#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas.casadm_parser import *
from api.cas.cli import *
from api.cas.statistics import CacheStats, CacheIoClassStats
from test_utils.os_utils import *


class Cache:
    def __init__(self, device: Device):
        self.cache_device = device
        self.cache_id = int(self.__get_cache_id())
        self.__cache_line_size = None
        self.__metadata_size = None

    def __get_cache_id(self):
        cmd = f"{list_cmd(by_id_path=False)} | grep {self.cache_device.get_device_id()}"
        output = TestRun.executor.run(cmd)
        if output.exit_code == 0 and output.stdout.strip():
            return output.stdout.split()[1]
        else:
            raise Exception(f"There is no cache started on {self.cache_device.get_device_id()}.")

    def get_core_devices(self):
        return get_cores(self.cache_id)

    def get_cache_line_size(self):
        if self.__cache_line_size is None:
            stats = self.get_statistics()
            stats_line_size = stats.config_stats.cache_line_size
            self.__cache_line_size = CacheLineSize(stats_line_size)
        return self.__cache_line_size

    def get_cleaning_policy(self):
        stats = self.get_statistics()
        cp = stats.config_stats.cleaning_policy
        return CleaningPolicy[cp]

    def get_metadata_size(self):
        if self.__metadata_size is None:
            stats = self.get_statistics()
            self.__metadata_size = stats.config_stats.metadata_memory_footprint
        return self.__metadata_size

    def get_occupancy(self):
        return self.get_statistics().usage_stats.occupancy

    def get_status(self):
        status = (
            self.get_statistics(stat_filter=[StatsFilter.conf])
            .config_stats.status.replace(" ", "_")
            .lower()
        )
        return CacheStatus[status]

    @property
    def size(self):
        return self.get_statistics().config_stats.cache_size

    def get_cache_mode(self):
        return CacheMode[self.get_statistics().config_stats.write_policy.upper()]

    def get_dirty_blocks(self):
        return self.get_statistics().usage_stats.dirty

    def get_dirty_for(self):
        return self.get_statistics().config_stats.dirty_for

    def get_clean_blocks(self):
        return self.get_statistics().usage_stats.clean

    def get_flush_parameters_alru(self):
        return get_flush_parameters_alru(self.cache_id)

    def get_flush_parameters_acp(self):
        return get_flush_parameters_acp(self.cache_id)

    # Casadm methods:

    def get_io_class_statistics(self,
                                io_class_id: int,
                                stat_filter: List[StatsFilter] = None,
                                percentage_val: bool = False):
        stats = get_statistics(self.cache_id, None, io_class_id,
                               stat_filter, percentage_val)
        return CacheIoClassStats(stats)

    def get_statistics(self,
                       stat_filter: List[StatsFilter] = None,
                       percentage_val: bool = False):
        stats = get_statistics(self.cache_id, None, None,
                               stat_filter, percentage_val)
        return CacheStats(stats)

    def get_statistics_flat(self,
                            io_class_id: int = None,
                            stat_filter: List[StatsFilter] = None,
                            percentage_val: bool = False):
        return get_statistics(self.cache_id, None, io_class_id,
                              stat_filter, percentage_val)

    def flush_cache(self):
        casadm.flush(cache_id=self.cache_id)
        sync()
        assert self.get_dirty_blocks().get_value(Unit.Blocks4096) == 0

    def purge_cache(self):
        casadm.purge_cache(cache_id=self.cache_id)
        sync()

    def stop(self, no_data_flush: bool = False):
        return casadm.stop_cache(self.cache_id, no_data_flush)

    def add_core(self, core_dev, core_id: int = None):
        return casadm.add_core(self, core_dev, core_id)

    def remove_core(self, core_id: int, force: bool = False):
        return casadm.remove_core(self.cache_id, core_id, force)

    def remove_inactive_core(self, core_id: int, force: bool = False):
        return casadm.remove_inactive(self.cache_id, core_id, force)

    def reset_counters(self):
        return casadm.reset_counters(self.cache_id)

    def set_cache_mode(self, cache_mode: CacheMode, flush=None):
        return casadm.set_cache_mode(cache_mode, self.cache_id, flush)

    def load_io_class(self, file_path: str):
        return casadm.load_io_classes(self.cache_id, file_path)

    def list_io_classes(self):
        return get_io_class_list(self.cache_id)

    def set_seq_cutoff_parameters(self, seq_cutoff_param: SeqCutOffParameters):
        return casadm.set_param_cutoff(self.cache_id,
                                       threshold=seq_cutoff_param.threshold,
                                       policy=seq_cutoff_param.policy,
                                       promotion_count=seq_cutoff_param.promotion_count)

    def set_seq_cutoff_threshold(self, threshold: Size):
        return casadm.set_param_cutoff(self.cache_id,
                                       threshold=threshold,
                                       policy=None)

    def set_seq_cutoff_policy(self, policy: SeqCutOffPolicy):
        return casadm.set_param_cutoff(self.cache_id,
                                       threshold=None,
                                       policy=policy)

    def set_cleaning_policy(self, cleaning_policy: CleaningPolicy):
        return casadm.set_param_cleaning(self.cache_id, cleaning_policy)

    def set_params_acp(self, acp_params: FlushParametersAcp):
        return casadm.set_param_cleaning_acp(self.cache_id,
                                             int(acp_params.wake_up_time.total_milliseconds())
                                             if acp_params.wake_up_time else None,
                                             int(acp_params.flush_max_buffers)
                                             if acp_params.flush_max_buffers else None)

    def set_params_alru(self, alru_params: FlushParametersAlru):
        return casadm.set_param_cleaning_alru(
            self.cache_id,
            int(alru_params.wake_up_time.total_seconds())
            if alru_params.wake_up_time is not None else None,
            int(alru_params.staleness_time.total_seconds())
            if alru_params.staleness_time is not None else None,
            alru_params.flush_max_buffers
            if alru_params.flush_max_buffers is not None else None,
            int(alru_params.activity_threshold.total_milliseconds())
            if alru_params.activity_threshold is not None else None)

    def get_cache_config(self):
        return CacheConfig(self.get_cache_line_size(),
                           self.get_cache_mode(),
                           self.get_cleaning_policy())

    def standby_detach(self, shortcut: bool = False):
        return casadm.standby_detach_cache(cache_id=self.cache_id, shortcut=shortcut)

    def standby_activate(self, device, shortcut: bool = False):
        return casadm.standby_activate_cache(
            cache_id=self.cache_id, cache_dev=device, shortcut=shortcut
        )
