#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
import pytest
from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CacheModeTrait, CleaningPolicy, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.os_utils import Udev
from test_utils.output import CmdException
from test_utils.size import Size, Unit
from tests.lazy_writes.recovery.recovery_tests_methods import create_test_files, copy_file, \
    compare_files, power_cycle_dut

mount_point = "/mnt"
test_file_size = Size(1.5, Unit.GibiByte)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_plugin("power_control")
def test_recovery_flush_reset_raw(cache_mode):
    """
        title: Recovery after reset during cache flushing - test on raw device.
        description: |
          Verify that unflushed data can be safely recovered, when reset was pressed during
          data flushing on raw device.
        pass_criteria:
          - CAS recovers successfully after reboot
          - No data corruption
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)] * 2)
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]
        core_device_link = core_device.get_device_link("/dev/disk/by-id")
        cache_device_link = cache_device.get_device_link("/dev/disk/by-id")

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)

    with TestRun.step("Setup cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode)
        core = cache.add_core(core_device)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path, target=core.system_path, size=test_file_size,
                  direct="oflag")

    with TestRun.step("Sync and flush buffers."):
        os_utils.sync()
        output = TestRun.executor.run(f"hdparm -f {core.system_path}")
        if output.exit_code != 0:
            raise CmdException("Error during hdparm", output)

    with TestRun.step("Trigger flush."):
        TestRun.executor.run_in_background(cli.flush_cache_cmd(f"{cache.cache_id}"))

    with TestRun.step("Hard reset DUT during data flushing."):
        power_cycle_dut(wait_for_flush_begin=True, core_device=core_device)
        cache_device.full_path = cache_device_link.get_target()
        core_device.full_path = core_device_link.get_target()

    with TestRun.step("Copy file from core and check if current md5sum is different than "
                      "before restart."):
        copy_file(source=core_device_link.get_target(), target=target_file.full_path,
                  size=test_file_size, direct="iflag")
        compare_files(source_file, target_file, should_differ=True)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        if cache.get_dirty_blocks() == Size.zero():
            TestRun.fail("There are no dirty blocks on cache device.")

    with TestRun.step("Stop cache with dirty data flush."):
        core_writes_before = core_device.get_io_stats().sectors_written
        cache.stop()
        if core_writes_before >= core_device.get_io_stats().sectors_written:
            TestRun.fail("No data was flushed after stopping cache started with load option.")

    with TestRun.step("Copy test file from core device to temporary location. "
                      "Compare it with the first version – they should be the same."):
        copy_file(source=core_device_link.get_target(), target=target_file.full_path,
                  size=test_file_size, direct="iflag")
        compare_files(source_file, target_file)

    with TestRun.step("Cleanup core device and remove test files."):
        target_file.remove()
        source_file.remove()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("fs", [Filesystem.xfs, Filesystem.ext4])
@pytest.mark.require_plugin("power_control")
def test_recovery_flush_reset_fs(cache_mode, fs):
    """
        title: Recovery after reset during cache flushing - test on filesystem.
        description: |
          Verify that unflushed data can be safely recovered, when reset was pressed during
          data flushing on filesystem.
        pass_criteria:
          - CAS recovers successfully after reboot
          - No data corruption
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)] * 2)
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]
        core_device_link = core_device.get_device_link("/dev/disk/by-id")
        cache_device_link = cache_device.get_device_link("/dev/disk/by-id")

    with TestRun.step(f"Create {fs} filesystem on core."):
        core_device.create_filesystem(fs)

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)

    with TestRun.step("Setup cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode)
        Udev.disable()
        core = cache.add_core(core_device)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Mount CAS device."):
        core.mount(mount_point)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path,
                  target=os.path.join(mount_point, "source_test_file"),
                  size=test_file_size, direct="oflag")

    with TestRun.step("Unmount CAS device."):
        core.unmount()

    with TestRun.step("Trigger flush."):
        TestRun.executor.run_in_background(cli.flush_cache_cmd(f"{cache.cache_id}"))

    with TestRun.step("Hard reset DUT during data flushing."):
        power_cycle_dut(True, core_device)
        cache_device.full_path = cache_device_link.get_target()
        core_device.full_path = core_device_link.get_target()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        if cache.get_dirty_blocks() == Size.zero():
            TestRun.fail("There are no dirty blocks on cache device.")

    with TestRun.step("Stop cache with dirty data flush."):
        core_writes_before = core_device.get_io_stats().sectors_written
        cache.stop()
        if core_writes_before >= core_device.get_io_stats().sectors_written:
            TestRun.fail("No data was flushed after stopping cache started with load option.")

    with TestRun.step("Mount core device."):
        core_device.mount(mount_point)

    with TestRun.step("Copy test file from core device to temporary location. "
                      "Compare it with the first version – they should be the same."):
        copy_file(source=os.path.join(mount_point, "source_test_file"),
                  target=target_file.full_path,
                  size=test_file_size, direct="iflag")
        compare_files(source_file, target_file)

    with TestRun.step("Unmount core device and remove test files."):
        core_device.unmount()
        target_file.remove()
        source_file.remove()
        Udev.enable()
