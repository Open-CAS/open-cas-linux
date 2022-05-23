#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from time import sleep

from api.cas import casadm
from api.cas.cache_config import (CacheMode,
                                  CacheModeTrait,
                                  CleaningPolicy,
                                  FlushParametersAlru,
                                  Time)
from storage_devices.disk import DiskType, DiskTypeSet
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from test_tools.fs_utils import create_random_test_file
from test_utils.scsi_debug import Logs, syslog_path
from test_utils import os_utils
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug_fua_signals", dev_size_mb="4096", opts="1")
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_signal_core(cache_mode):
    """
        title: Test for FLUSH nad FUA signals sent to core device in modes with lazy writes.
        description: |
          Test if OpenCAS transmits FLUSH and FUA signals to core device in modes with lazy writes.
        pass_criteria:
          - FLUSH requests should be passed to core device.
          - FUA requests should be passed to core device.
    """
    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        Logs._read_syslog(Logs.last_read_line)

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.scsi_debug_devices[0]

    with TestRun.step("Start cache and add SCSI device with xfs filesystem as core."):
        cache = casadm.start_cache(cache_part, cache_mode)
        core_dev.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_dev)

    with TestRun.step("Mount exported object."):
        if core.is_mounted():
            core.unmount()
        core.mount(mount_point)

    with TestRun.step("Turn off cleaning policy."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Flush cache."):
        cache.flush_cache()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Flush core."):
        core.flush_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Turn on alru cleaning policy and set policy params."):
        cache.set_cleaning_policy(CleaningPolicy.alru)
        cache.set_params_alru(FlushParametersAlru(
            Time(milliseconds=5000), 10000, Time(seconds=10), Time(seconds=10))
        )

    with TestRun.step("Create big temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(5, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Wait for automatic flush from alru cleaning policy and check log."):
        wait_time = (
            int(cache.get_flush_parameters_alru().staleness_time.total_seconds())
            + int(cache.get_flush_parameters_alru().activity_threshold.total_seconds())
            + int(cache.get_flush_parameters_alru().wake_up_time.total_seconds())
            + 5
        )
        sleep(wait_time)

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on exported object."):
        create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Unmount exported object and remove it from cache."):
        core.unmount()
        core.remove_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request."):
        Logs.check_syslog_for_signals()

    with TestRun.step("Stop cache."):
        cache.stop()


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug_fua_signals", dev_size_mb="2048", opts="1")
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
def test_flush_signal_cache(cache_mode):
    """
        title: Test for FLUSH and FUA signals sent to cache device in modes with lazy writes.
        description: |
          Test if OpenCAS transmits FLUSH and FUA signals to cache device in modes with lazy writes.
        pass_criteria:
          - FLUSH requests should be passed to cache device.
          - FUA requests should be passed to cache device.
    """
    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        Logs._read_syslog(Logs.last_read_line)

    with TestRun.step("Prepare devices for cache and core."):
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]
        cache_dev = TestRun.scsi_debug_devices[0]

    with TestRun.step("Start SCSI device as cache and add core with xfs filesystem."):
        cache = casadm.start_cache(cache_dev, cache_mode)
        core_part.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_part)

    with TestRun.step("Mount exported object."):
        if core.is_mounted():
            core.unmount()
        core.mount(mount_point)

    with TestRun.step("Turn off cleaning policy."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Flush cache."):
        cache.flush_cache()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush and FUA requests and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Flush core."):
        core.flush_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Turn on alru cleaning policy and set policy params."):
        cache.set_cleaning_policy(CleaningPolicy.alru)
        cache.set_params_alru(FlushParametersAlru(
            Time(milliseconds=5000), 10000, Time(seconds=10), Time(seconds=10))
        )

    with TestRun.step("Create big temporary file on exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(5, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Wait for automatic flush from alru cleaning policy and check log."):
        wait_time = (
            int(cache.get_flush_parameters_alru().staleness_time.total_seconds())
            + int(cache.get_flush_parameters_alru().activity_threshold.total_seconds())
            + int(cache.get_flush_parameters_alru().wake_up_time.total_seconds())
            + 5
        )
        sleep(wait_time)

    with TestRun.step(f"Check {syslog_path} for flush and FUA requests and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on exported object."):
        create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Unmount exported object and remove it from cache."):
        core.unmount()
        core.remove_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush and FUA requests."):
        Logs.check_syslog_for_signals()

    with TestRun.step("Stop cache."):
        cache.stop()


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug_fua_signals", dev_size_mb="2048", opts="1")
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_signal_multilevel_cache(cache_mode):
    """
        title: Test for FLUSH and FUA signals sent to multilevel cache in modes with lazy writes.
        description: |
          Test if OpenCAS transmits FLUSH and FUA signals with multilevel cache in lazy-write modes.
        pass_criteria:
          - FLUSH requests should be passed by multilevel cache to core device.
          - FUA requests should be passed by multilevel cache to core device.
    """
    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        Logs._read_syslog(Logs.last_read_line)

    with TestRun.step("Prepare devices for multilevel cache."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)] * 2)
        cache_part1 = cache_dev.partitions[0]
        cache_part2 = cache_dev.partitions[1]
        core_dev = TestRun.scsi_debug_devices[0]

    with TestRun.step("Start the first cache and add the SCSI device as a core."):
        cache1 = casadm.start_cache(cache_part1, cache_mode)
        core1 = cache1.add_core(core_dev)

    with TestRun.step("Start the second cache and add the 1st exported object as core."):
        cache2 = casadm.start_cache(cache_part2, cache_mode)
        core2 = cache2.add_core(core1)

    with TestRun.step("Create xfs filesystem on the 2nd exported object and mount it."):
        core2.create_filesystem(Filesystem.xfs)
        if core2.is_mounted():
            core2.unmount()
        core2.mount(mount_point)

    with TestRun.step("Turn off cleaning policy on both caches."):
        cache1.set_cleaning_policy(CleaningPolicy.nop)
        cache2.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create temporary file on the 2nd exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(512, Unit.MebiByte))
        os_utils.sync()

    with TestRun.step("Flush both caches."):
        cache2.flush_cache()
        cache1.flush_cache()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush and FUA requests and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on the 2nd exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(512, Unit.MebiByte))
        os_utils.sync()

    with TestRun.step("Flush both cores."):
        core2.flush_core()
        core1.flush_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Turn on alru cleaning policy and set policy params on both caches."):
        cache1.set_cleaning_policy(CleaningPolicy.alru)
        cache1.set_params_alru(FlushParametersAlru(
            Time(milliseconds=5000), 10000, Time(seconds=10), Time(seconds=10))
        )
        cache2.set_cleaning_policy(CleaningPolicy.alru)
        cache2.set_params_alru(FlushParametersAlru(
            Time(milliseconds=5000), 10000, Time(seconds=10), Time(seconds=10))
        )

    with TestRun.step("Create big temporary file on the 2nd exported object."):
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(3, Unit.GibiByte))
        os_utils.sync()

    with TestRun.step("Wait for automatic flush from alru cleaning policy and check log."):
        wait_time = (
            int(cache2.get_flush_parameters_alru().staleness_time.total_seconds())
            + int(cache2.get_flush_parameters_alru().activity_threshold.total_seconds())
            + int(cache2.get_flush_parameters_alru().wake_up_time.total_seconds())
            + 5
        )
        sleep(wait_time)

    with TestRun.step(f"Check {syslog_path} for flush and FUA requests and delete temporary file."):
        Logs.check_syslog_for_signals()
        tmp_file.remove(True)

    with TestRun.step("Create temporary file on the 2nd exported object."):
        create_random_test_file(f"{mount_point}/tmp.file", Size(512, Unit.MebiByte))
        os_utils.sync()

    with TestRun.step("Unmount the 2nd exported object and remove cores from caches."):
        core2.unmount()
        core2.remove_core()
        core1.remove_core()
        os_utils.sync()

    with TestRun.step(f"Check {syslog_path} for flush request."):
        Logs.check_syslog_for_signals()

    with TestRun.step("Stop both caches."):
        cache2.stop()
        cache1.stop()
