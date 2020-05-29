#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait, SeqCutOffPolicy
from storage_devices.device import Device
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fs_utils import create_random_test_file, remove
from test_tools.iostat import IOstatBasic
from test_utils.filesystem.file import File
from test_utils.os_utils import Udev, sync
from test_utils.size import Size, Unit

bs = Size(512, Unit.KibiByte)
mnt_point = "/mnt/cas/"


@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_clean_stop_cache(cache_mode):
    """
        title: Test of the ability to stop cache in modes with lazy writes.
        description: |
          Test if OpenCAS stops cache in modes with lazy writes without data loss.
        pass_criteria:
          - Cache stopping works properly.
          - Writes to exported object and core device during OpenCAS's work are equal
          - Data on core device is correct after cache is stopped.
    """
    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(256, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(512, Unit.MebiByte)])
        core_part = core_dev.partitions[0]
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} mode."):
        cache = casadm.start_cache(cache_part, cache_mode)

    with TestRun.step("Add core to cache."):
        core = cache.add_core(core_part)

    with TestRun.step("Disable cleaning and sequential cutoff."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Read IO stats before test"):
        core_disk_writes_initial = check_device_write_stats(core_part)
        exp_obj_writes_initial = check_device_write_stats(core)

    with TestRun.step("Write data to the exported object."):
        test_file_main = create_random_test_file("/tmp/test_file_main", Size(64, Unit.MebiByte))
        dd = Dd().output(core.system_path) \
            .input(test_file_main.full_path) \
            .block_size(bs) \
            .count(int(test_file_main.size / bs)) \
            .oflag("direct")
        dd.run()
        test_file_md5sum_main = test_file_main.md5sum()

    with TestRun.step("Read IO stats after write to the exported object."):
        core_disk_writes_increase = (
            check_device_write_stats(core_part) - core_disk_writes_initial
        )
        exp_obj_writes_increase = (
            check_device_write_stats(core) - exp_obj_writes_initial
        )

    with TestRun.step("Validate IO stats after write to the exported object."):
        if core_disk_writes_increase > 0:
            TestRun.LOGGER.error("Writes should occur only on the exported object.")
        if exp_obj_writes_increase != test_file_main.size.value:
            TestRun.LOGGER.error("Not all writes reached the exported object.")

    with TestRun.step("Read data from the exported object."):
        test_file_1 = File.create_file("/tmp/test_file_1")
        dd = Dd().output(test_file_1.full_path) \
            .input(core.system_path) \
            .block_size(bs) \
            .count(int(test_file_main.size / bs)) \
            .oflag("direct")
        dd.run()
        test_file_1.refresh_item()
        sync()

    with TestRun.step("Compare md5 sum of test files."):
        if test_file_md5sum_main != test_file_1.md5sum():
            TestRun.LOGGER.error("Md5 sums should be equal.")

    with TestRun.step("Read data from the core device."):
        test_file_2 = File.create_file("/tmp/test_file_2")
        dd = Dd().output(test_file_2.full_path) \
            .input(core_part.system_path) \
            .block_size(bs) \
            .count(int(test_file_main.size / bs)) \
            .oflag("direct")
        dd.run()
        test_file_2.refresh_item()
        sync()

    with TestRun.step("Compare md5 sum of test files."):
        if test_file_md5sum_main == test_file_2.md5sum():
            TestRun.LOGGER.error("Md5 sums should be different.")

    with TestRun.step("Read IO stats before stopping cache."):
        core_disk_writes_before_stop = check_device_write_stats(core_part)

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Read IO stats after stopping cache."):
        core_disk_writes_increase = (
            check_device_write_stats(core_part) - core_disk_writes_before_stop
        )

    with TestRun.step("Validate IO stats after stopping cache."):
        if core_disk_writes_increase == 0:
            TestRun.LOGGER.error("Writes should occur on the core device after stopping cache.")
        if core_disk_writes_increase != exp_obj_writes_increase:
            TestRun.LOGGER.error("Write statistics for the core device should be equal "
                                 "to those from the exported object.")

    with TestRun.step("Read data from the core device."):
        test_file_3 = File.create_file("/tmp/test_file_2")
        dd = Dd().output(test_file_3.full_path) \
            .input(core_part.system_path) \
            .block_size(bs) \
            .count(int(test_file_main.size / bs)) \
            .oflag("direct")
        dd.run()
        test_file_3.refresh_item()
        sync()

    with TestRun.step("Compare md5 sum of test files."):
        if test_file_md5sum_main != test_file_3.md5sum():
            TestRun.LOGGER.error("Md5 sums should be equal.")

    with TestRun.step("Delete test files."):
        test_file_main.remove(True)
        test_file_1.remove(True)
        test_file_2.remove(True)
        test_file_3.remove(True)




def check_device_write_stats(device: Device):
    return IOstatBasic.get_iostat_list(devices_list=[device])[0].total_writes.value
