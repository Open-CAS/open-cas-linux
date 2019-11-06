#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
from typing import List

from api.cas.cli import *
from api.cas.casadm_parser import *
from api.cas.cache import Device
from test_utils.os_utils import *


class CoreStatus(Enum):
    empty = 0,
    active = 1,
    inactive = 2,
    detached = 3


SEQ_CUTOFF_THRESHOLD_MAX = 4194181


class Core(Device):
    def __init__(self, core_device: str, cache_id: int):
        self.core_device = Device(core_device)
        self.system_path = None
        core_info = self.__get_core_info()
        self.core_id = int(core_info["core_id"])
        Device.__init__(self, core_info["exp_obj"])
        self.cache_id = cache_id

    def __get_core_info(self):
        output = TestRun.executor.run(
            list_cmd(OutputFormat.csv.name))
        if output.exit_code != 0:
            raise Exception("Failed to execute list caches command.")
        output_lines = output.stdout.splitlines()
        for line in output_lines:
            split_line = line.split(',')
            if split_line[0] == "core" and (split_line[2] == self.core_device.system_path
                                            or split_line[5] == self.system_path):
                return {"core_id": split_line[1],
                        "core_device": split_line[2],
                        "status": split_line[3],
                        "exp_obj": split_line[5]}

    def get_core_statistics(self,
                            io_class_id: int = None,
                            stat_filter: List[StatsFilter] = None,
                            percentage_val: bool = False):
        return get_statistics(self.cache_id, self.core_id, io_class_id,
                              stat_filter, percentage_val)

    def get_status(self):
        return self.__get_core_info()["status"]

    def get_seq_cut_off_parameters(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id)

    def get_seq_cut_off_policy(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id).policy

    def get_seq_cut_off_threshold(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id).threshold

    def get_dirty_blocks(self):
        return self.get_core_statistics()["dirty"]

    def get_clean_blocks(self):
        return self.get_core_statistics()["clean"]

    def get_occupancy(self):
        return self.get_core_statistics()["occupancy"]

    # Casadm methods:

    def remove_core(self, force: bool = False):
        return casadm.remove_core(self.cache_id, self.core_id, force)

    def reset_counters(self):
        return casadm.reset_counters(self.cache_id, self.core_id)

    def flush_core(self):
        casadm.flush(self.cache_id, self.core_id)
        sync()
        assert self.get_dirty_blocks().get_value(Unit.Blocks4096) == 0

    def set_seq_cutoff_parameters(self, seq_cutoff_param: SeqCutOffParameters):
        return casadm.set_param_cutoff(self.cache_id, self.core_id,
                                       seq_cutoff_param.threshold, seq_cutoff_param.policy)

    def set_seq_cutoff_threshold(self, threshold: Size):
        return casadm.set_param_cutoff(self.cache_id, self.core_id,
                                       threshold=threshold,
                                       policy=None)

    def set_seq_cutoff_policy(self, policy: SeqCutOffPolicy):
        return casadm.set_param_cutoff(self.cache_id, self.core_id,
                                       threshold=None,
                                       policy=policy)
