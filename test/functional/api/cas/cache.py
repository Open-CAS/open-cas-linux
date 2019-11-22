#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from api.cas.cli import *
from api.cas.casadm_parser import *
from test_utils.os_utils import *
from api.cas.cache_config import *
from storage_devices.device import Device
from core.test_run import TestRun
from api.cas.casadm_params import *


class Cache:
    def __init__(self, device_system_path):
        self.cache_device = Device(device_system_path)
        self.cache_id = int(self.__get_cache_id())
        self.__cache_line_size = None
        self.__metadata_mode = None
        self.__metadata_size = None

    def __get_cache_id(self):
        cmd = f"{list_cmd()} | grep {self.cache_device.system_path}"
        output = TestRun.executor.run(cmd)
        if output.exit_code == 0 and output.stdout.strip():
            return output.stdout.split()[1]
        else:
            raise Exception(f"There is no cache started on {self.cache_device.system_path}.")

    def get_core_devices(self):
        return get_cores(self.cache_id)

    def get_cache_line_size(self):
        if self.__cache_line_size is None:
            stats = self.get_cache_statistics()
            stats_line_size = stats["cache line size"]
            self.__cache_line_size = CacheLineSize(stats_line_size.get_value(Unit.Byte))
        return self.__cache_line_size

    def get_cleaning_policy(self):
        stats = self.get_cache_statistics()
        cp = stats["cleaning policy"]
        return CleaningPolicy[cp]

    def get_eviction_policy(self):
        stats = self.get_cache_statistics()
        ep = stats["eviction policy"]
        return EvictionPolicy[ep]

    def get_metadata_mode(self):
        if self.__metadata_mode is None:
            stats = self.get_cache_statistics()
            mm = stats["metadata mode"]
            self.__metadata_mode = MetadataMode[mm]
        return self.__metadata_mode

    def get_metadata_size(self):
        if self.__metadata_size is None:
            stats = self.get_cache_statistics()
            self.__metadata_size = stats["metadata memory footprint"]
        return self.__metadata_size

    def get_occupancy(self):
        return self.get_cache_statistics()["occupancy"]

    def get_status(self):
        status = self.get_cache_statistics()["status"].replace(' ', '_')
        return CacheStatus[status]

    def get_cache_mode(self):
        return CacheMode[self.get_cache_statistics()["write policy"].upper()]

    def get_dirty_blocks(self):
        return self.get_cache_statistics()["dirty"]

    def get_dirty_for(self):
        return self.get_cache_statistics()["dirty for"]

    def get_clean_blocks(self):
        return self.get_cache_statistics()["clean"]

    def get_flush_parameters_alru(self):
        return get_flush_parameters_alru(self.cache_id)

    def get_flush_parameters_acp(self):
        return get_flush_parameters_acp(self.cache_id)

    # Casadm methods:

    def get_cache_statistics(self,
                             io_class_id: int = None,
                             stat_filter: List[StatsFilter] = None,
                             percentage_val: bool = False):
        return get_statistics(self.cache_id, None, io_class_id,
                              stat_filter, percentage_val)

    def flush_cache(self):
        casadm.flush(cache_id=self.cache_id)
        sync()
        assert self.get_dirty_blocks().get_value(Unit.Blocks4096) == 0

    def stop(self, no_data_flush: bool = False):
        return casadm.stop_cache(self.cache_id, no_data_flush)

    def add_core(self, core_dev, core_id: int = None):
        return casadm.add_core(self, core_dev, core_id)

    def remove_core(self, core_id, force: bool = False):
        return casadm.remove_core(self.cache_id, core_id, force)

    def reset_counters(self):
        return casadm.reset_counters(self.cache_id)

    def set_cache_mode(self, cache_mode: CacheMode, flush=None):
        return casadm.set_cache_mode(cache_mode, self.cache_id, flush)

    def load_io_class(self, file_path: str):
        return casadm.load_io_classes(self.cache_id, file_path)

    def list_io_classes(self, output_format: OutputFormat):
        return casadm.list_io_classes(self.cache_id, output_format)

    def set_seq_cutoff_parameters(self, seq_cutoff_param: SeqCutOffParameters):
        return casadm.set_param_cutoff(self.cache_id,
                                       seq_cutoff_param.threshold,
                                       seq_cutoff_param.policy)

    def set_cleaning_policy(self, cleaning_policy: CleaningPolicy):
        return casadm.set_param_cleaning(self.cache_id, cleaning_policy)

    def set_params_acp(self, acp_params: FlushParametersAcp):
        return casadm.set_param_cleaning_acp(self.cache_id,
                                             acp_params.wake_up_time.total_milliseconds(),
                                             acp_params.flush_max_buffers)

    def set_params_alru(self, alru_params: FlushParametersAlru):
        return casadm.set_param_cleaning_alru(self.cache_id,
                                              alru_params.wake_up_time.total_seconds(),
                                              alru_params.staleness_time.total_seconds(),
                                              alru_params.flush_max_buffers,
                                              alru_params.activity_threshold.total_milliseconds())

    def get_cache_config(self):
        return CacheConfig(self.get_cache_line_size(),
                           self.get_cache_mode(),
                           self.get_cleaning_policy(),
                           self.get_eviction_policy(),
                           self.get_metadata_mode())
