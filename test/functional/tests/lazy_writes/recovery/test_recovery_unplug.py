#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os

import pytest

from api.cas import casadm, cli_messages
from api.cas.cache_config import CacheMode, CacheModeTrait, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_utils.output import CmdException
from test_utils.size import Size, Unit
from tests.lazy_writes.recovery.recovery_tests_methods import create_test_files, copy_file, \
    compare_files

test_file_size = Size(0.5, Unit.GibiByte)
mount_point = "/mnt"
test_file_path = os.path.join(mount_point, "test_file")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("direct", [True, False])
@pytest.mark.require_plugin("power_control")
def test_recovery_unplug_cache_fs(cache_mode, cls, filesystem, direct):
    """
            title: Test for recovery after cache drive removal - test with filesystem.
            description: |
              Verify that unflushed data can be safely recovered after, when SSD drive is removed
              after write completion - test with filesystem.
            pass_criteria:
              - CAS recovers successfully after cache drive unplug
              - No data corruption
    """
    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)])
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)
        source_file_md5 = source_file.md5sum()

    with TestRun.step("Create filesystem on core device."):
        core_device.create_filesystem(filesystem)

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode, cls)
        core = cache.add_core(core_device)

    with TestRun.step("Mount CAS device."):
        core.mount(mount_point)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path, target=test_file_path,
                  size=test_file_size, direct="oflag" if direct else None)
        TestRun.LOGGER.info(str(core.get_statistics()))

    with TestRun.step("Unmount CAS device."):
        core.unmount()

    with TestRun.step("Unplug cache device."):
        cache_disk.unplug()
        TestRun.LOGGER.info(f"List caches:\n{casadm.list_caches().stdout}")
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache."):
        try:
            cache.stop()
            TestRun.fail("Stopping the cache should be aborted without --no-flush flag.")
        except CmdException as e:
            TestRun.LOGGER.info(str(e.output))
            try:
                cache.stop(no_data_flush=True)
                TestRun.LOGGER.warning("Expected stopping cache with errors with --no-flush flag.")
            except CmdException as e1:
                cli_messages.check_stderr_msg(e1.output, cli_messages.stop_cache_errors)

    with TestRun.step("Plug missing cache device."):
        TestRun.LOGGER.info(str(casadm.list_caches(by_id_path=False)))
        cache_disk.plug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache with data flush."):
        cache.stop()

    with TestRun.step("Mount core device."):
        core_device.mount(mount_point)

    with TestRun.step("Copy file from core device and check md5sum."):
        copy_file(source=test_file_path, target=target_file.full_path,
                  size=test_file_size, direct="iflag" if direct else None)
        target_file_md5 = target_file.md5sum()
        compare_files(source_file_md5, target_file_md5)

    with TestRun.step("Unmount core device and remove files."):
        core_device.unmount()
        try:
            target_file.remove()
            source_file.remove()
        except Exception:
            # On some OSes files at /tmp location are automatically removed after DUT hard reset
            pass


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.require_plugin("power_control")
def test_recovery_unplug_cache_raw(cache_mode, cls):
    """
            title: Test for recovery after cache drive removal - test on raw device.
            description: |
              Verify that unflushed data can be safely recovered after, when SSD drive is removed
              after write completion - test on raw device.
            pass_criteria:
              - CAS recovers successfully after cache drive unplug
              - No data corruption
    """
    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(16, Unit.GibiByte)])
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]

    with TestRun.step("Create test files."):
        source_file, target_file = create_test_files(test_file_size)
        source_file_md5 = source_file.md5sum()

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode, cls, force=True)
        core = cache.add_core(core_device)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path, target=core.path,
                  size=test_file_size, direct="oflag")
        TestRun.LOGGER.info(str(core.get_statistics()))

    with TestRun.step("Unplug cache device."):
        cache_disk.unplug()
        TestRun.LOGGER.info(f"List caches:\n{casadm.list_caches().stdout}")
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache."):
        try:
            cache.stop()
            TestRun.fail("Stopping the cache should be aborted without --no-flush flag.")
        except CmdException as e:
            TestRun.LOGGER.info(str(e.output))
            try:
                cache.stop(no_data_flush=True)
                TestRun.LOGGER.warning("Expected stopping cache with errors with --no-flush flag.")
            except CmdException as e1:
                cli_messages.check_stderr_msg(e1.output, cli_messages.stop_cache_errors)

    with TestRun.step("Plug missing cache device."):
        TestRun.LOGGER.info(str(casadm.list_caches(by_id_path=False)))
        cache_disk.plug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache with data flush."):
        cache.stop()

    with TestRun.step("Copy file from core device and check md5sum."):
        copy_file(source=core_device.path, target=target_file.full_path,
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
