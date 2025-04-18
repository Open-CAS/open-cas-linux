#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta
from typing import List

from api.cas import casadm
from api.cas.cache_config import SeqCutOffParameters, SeqCutOffPolicy
from api.cas.casadm_params import StatsFilter
from api.cas.casadm_parser import get_seq_cut_off_parameters, get_cas_devices_dict
from api.cas.core_config import CoreStatus
from api.cas.statistics import CoreStats, CoreIoClassStats
from core.test_run_utils import TestRun
from storage_devices.device import Device
from test_tools.fs_tools import Filesystem, ls_item
from test_tools.os_tools import sync
from test_tools.common.wait import wait
from type_def.size import Unit, Size


SEQ_CUTOFF_THRESHOLD_MAX = Size(4194181, Unit.KibiByte)
SEQ_CUT_OFF_THRESHOLD_DEFAULT = Size(1, Unit.MebiByte)


class Core(Device):
    def __init__(self, core_device: str, cache_id: int):
        self.core_device = Device(core_device)
        self.path = None
        self.cache_id = cache_id
        core_info = self.__get_core_info()
        # "-" is special case for cores in core pool
        if core_info["core_id"] != "-":
            self.core_id = int(core_info["core_id"])
        if core_info["exp_obj"] != "-":
            Device.__init__(self, core_info["exp_obj"])
        self.partitions = []
        self.block_size = None

    def __get_core_info(self) -> dict | None:
        core_dicts = get_cas_devices_dict()["cores"].values()
        # for core
        core_device = [
            core
            for core in core_dicts
            if core["cache_id"] == self.cache_id and core["device_path"] == self.core_device.path
        ]
        if core_device:
            return core_device[0]

        # for core pool
        core_pool_dicts = get_cas_devices_dict()["core_pool"].values()
        core_pool_device = [
            core for core in core_pool_dicts if core["device_path"] == self.core_device.path
        ]
        return core_pool_device[0]

    def create_filesystem(self, fs_type: Filesystem, force=True, blocksize=None):
        super().create_filesystem(fs_type, force, blocksize)
        self.core_device.filesystem = self.filesystem

    def get_io_class_statistics(
        self,
        io_class_id: int,
        stat_filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ) -> CoreIoClassStats:
        return CoreIoClassStats(
            cache_id=self.cache_id,
            core_id=self.core_id,
            filter=stat_filter,
            io_class_id=io_class_id,
            percentage_val=percentage_val,
        )

    def get_statistics(
        self, stat_filter: List[StatsFilter] = None, percentage_val: bool = False
    ) -> CoreStats:
        return CoreStats(
            cache_id=self.cache_id,
            core_id=self.core_id,
            filter=stat_filter,
            percentage_val=percentage_val,
        )

    def get_status(self) -> CoreStatus:
        return self.__get_core_info()["status"]

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

    def remove_inactive(self, force: bool = False):
        return casadm.remove_inactive(self.cache_id, self.core_id, force)

    def reset_counters(self):
        return casadm.reset_counters(self.cache_id, self.core_id)

    def flush_core(self):
        casadm.flush_core(self.cache_id, self.core_id)
        sync()

    def purge_core(self):
        casadm.purge_core(self.cache_id, self.core_id)
        sync()

    def set_seq_cutoff_parameters(self, seq_cutoff_param: SeqCutOffParameters):
        return casadm.set_param_cutoff(
            self.cache_id,
            self.core_id,
            seq_cutoff_param.threshold,
            seq_cutoff_param.policy,
            seq_cutoff_param.promotion_count,
        )

    def set_seq_cutoff_threshold(self, threshold: Size):
        return casadm.set_param_cutoff(self.cache_id, self.core_id, threshold=threshold)

    def set_seq_cutoff_policy(self, policy: SeqCutOffPolicy):
        return casadm.set_param_cutoff(self.cache_id, self.core_id, policy=policy)

    def set_seq_cutoff_promotion_count(self, promotion_count: int):
        return casadm.set_param_cutoff(self.cache_id, self.core_id, promotion_count=promotion_count)

    def check_if_is_present_in_os(self, should_be_visible=True):
        device_in_system_message = "CAS device exists in OS."
        device_not_in_system_message = "CAS device does not exist in OS."
        item = ls_item(self.path)
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
