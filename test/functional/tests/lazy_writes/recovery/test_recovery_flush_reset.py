#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os

import pytest

from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CacheModeTrait, CleaningPolicy, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_tools.fs_utils import readlink
from test_utils import os_utils
from test_utils.os_utils import Udev, DropCachesMode
from test_utils.output import CmdException
from test_utils.size import Size, Unit
from tests.lazy_writes.recovery.recovery_tests_methods import create_test_files, copy_file, \
    compare_files, power_cycle_dut

mount_point = "/mnt"
test_file_size = Size(4.5, Unit.GibiByte)


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
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)] * 2)
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)
        source_file_md5 = source_file.md5sum()

    with TestRun.step("Setup cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode)
        core = cache.add_core(core_device)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path, target=core.path, size=test_file_size,
                  direct="oflag")

    with TestRun.step("Sync and flush buffers."):
        os_utils.sync()
        output = TestRun.executor.run(f"hdparm -f {core.path}")
        if output.exit_code != 0:
            raise CmdException("Error during hdparm", output)

    with TestRun.step("Trigger flush."):
        os_utils.drop_caches(DropCachesMode.ALL)
        TestRun.executor.run_in_background(cli.flush_cache_cmd(f"{cache.cache_id}"))

    with TestRun.step("Hard reset DUT during data flushing."):
        power_cycle_dut(wait_for_flush_begin=True, core_device=core_device)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        if cache.get_dirty_blocks() == Size.zero():
            TestRun.LOGGER.error("There are no dirty blocks on cache device.")

    with TestRun.step("Stop cache with dirty data flush."):
        core_writes_before = core_device.get_io_stats().sectors_written
        cache.stop()
        if core_writes_before >= core_device.get_io_stats().sectors_written:
            TestRun.fail("No data was flushed after stopping cache started with load option.")

    with TestRun.step("Copy test file from core device to temporary location. "
                      "Compare it with the first version – they should be the same."):
        copy_file(source=readlink(core_device.path), target=target_file.full_path,
                  size=test_file_size, direct="iflag")
        target_file_md5 = target_file.md5sum()
        compare_files(source_file_md5, target_file_md5)

    with TestRun.step("Cleanup core device and remove test files."):
        try:
            target_file.remove()
            source_file.remove()
        except Exception:
            # On some OSes files at /tmp location are automatically removed after DUT hard reset
            pass


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
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)] * 2)
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]

    with TestRun.step(f"Create {fs} filesystem on core."):
        core_device.create_filesystem(fs)

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)
        source_file_md5 = source_file.md5sum()

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
        os_utils.drop_caches(DropCachesMode.ALL)
        TestRun.executor.run_in_background(cli.flush_cache_cmd(f"{cache.cache_id}"))

    with TestRun.step("Hard reset DUT during data flushing."):
        power_cycle_dut(True, core_device)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        if cache.get_dirty_blocks() == Size.zero():
            TestRun.LOGGER.error("There are no dirty blocks on cache device.")

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
        target_file_md5 = target_file.md5sum()
        compare_files(source_file_md5, target_file_md5)

    with TestRun.step("Unmount core device and remove test files."):
        core_device.unmount()
        try:
            target_file.remove()
            source_file.remove()
        except Exception:
            # On some OSes files at /tmp location are automatically removed after DUT hard reset
            pass
        Udev.enable()
