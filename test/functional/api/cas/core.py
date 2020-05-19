#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


from api.cas.casadm_parser import *
from api.cas.cli import *
from api.cas.statistics import CoreStats, CoreIoClassStats
from test_tools import fs_utils, disk_utils
from test_utils.os_utils import *
from test_utils.os_utils import wait


class CoreStatus(Enum):
    empty = 0,
    active = 1,
    inactive = 2,
    detached = 3


SEQ_CUTOFF_THRESHOLD_MAX = Size(4194181, Unit.KibiByte)
SEQ_CUT_OFF_THRESHOLD_DEFAULT = Size(1, Unit.MebiByte)


class Core(Device):
    def __init__(self, core_device: str, cache_id: int):
        self.core_device = Device(core_device)
        self.system_path = None
        core_info = self.__get_core_info()
        if core_info["core_id"] != "-":
            self.core_id = int(core_info["core_id"])
        if core_info["exp_obj"] != "-":
            Device.__init__(self, core_info["exp_obj"])
        self.cache_id = cache_id
        self.partitions = []
        self.block_size = None

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

    def create_filesystem(self, fs_type: disk_utils.Filesystem, force=True, blocksize=None):
        super().create_filesystem(fs_type, force, blocksize)
        self.core_device.filesystem = self.filesystem

    def get_io_class_statistics(self,
                                io_class_id: int,
                                stat_filter: List[StatsFilter] = None,
                                percentage_val: bool = False):
        stats = get_statistics(self.cache_id, self.core_id, io_class_id,
                               stat_filter, percentage_val)
        return CoreIoClassStats(stats)

    def get_statistics(self,
                       stat_filter: List[StatsFilter] = None,
                       percentage_val: bool = False):
        stats = get_statistics(self.cache_id, self.core_id, None,
                               stat_filter, percentage_val)
        return CoreStats(stats)

    def get_statistics_flat(self,
                            io_class_id: int = None,
                            stat_filter: List[StatsFilter] = None,
                            percentage_val: bool = False):
        return get_statistics(self.cache_id, self.core_id, io_class_id,
                              stat_filter, percentage_val)

    def get_status(self):
        return CoreStatus[self.__get_core_info()["status"].lower()]

    def get_seq_cut_off_parameters(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id)

    def get_seq_cut_off_policy(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id).policy

    def get_seq_cut_off_threshold(self):
        return get_seq_cut_off_parameters(self.cache_id, self.core_id).threshold

    def get_dirty_blocks(self):
        return self.get_statistics().usage_stats.dirty

    def get_clean_blocks(self):
        return self.get_statistics().usage_stats.clean

    def get_occupancy(self):
        return self.get_statistics().usage_stats.occupancy

    # Casadm methods:

    def remove_core(self, force: bool = False):
        return casadm.remove_core(self.cache_id, self.core_id, force)

    def reset_counters(self):
        return casadm.reset_counters(self.cache_id, self.core_id)

    def flush_core(self):
        casadm.flush(self.cache_id, self.core_id)
        sync()
        assert self.get_dirty_blocks().get_value(Unit.Blocks4096) == 0

    def purge_core(self):
        casadm.purge_core(self.cache_id, self.core_id)
        sync()

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

    def check_if_is_present_in_os(self, should_be_visible=True):
        device_in_system_message = "CAS device exists in OS."
        device_not_in_system_message = "CAS device does not exist in OS."
        item = fs_utils.ls_item(f"{self.system_path}")
        if item is not None:
            if should_be_visible:
                TestRun.LOGGER.info(device_in_system_message)
            else:
                TestRun.fail(device_in_system_message)
        else:
            if should_be_visible:
                TestRun.fail(device_not_in_system_message)
            else:
                TestRun.LOGGER.info(device_not_in_system_message)

    def wait_for_status_change(self, expected_status: CoreStatus):
        timeout = timedelta(minutes=1)
        if not wait(lambda: self.get_status() == expected_status, timeout, timedelta(seconds=1)):
            TestRun.fail(f"Core status did not change after {timeout.total_seconds()}s.")
