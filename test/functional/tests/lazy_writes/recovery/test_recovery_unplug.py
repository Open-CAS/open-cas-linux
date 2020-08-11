#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
import pytest
from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
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
        cache.stop()

    with TestRun.step("Plug missing cache device."):
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
        compare_files(source_file, target_file)

    with TestRun.step("Unmount core device and remove files."):
        core_device.unmount()
        target_file.remove()
        source_file.remove()


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

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_device, cache_mode, cls)
        core = cache.add_core(core_device)

    with TestRun.step("Copy file to CAS."):
        copy_file(source=source_file.full_path, target=core.system_path,
                  size=test_file_size, direct="oflag")
        TestRun.LOGGER.info(str(core.get_statistics()))

    with TestRun.step("Unplug cache device."):
        cache_disk.unplug()
        TestRun.LOGGER.info(f"List caches:\n{casadm.list_caches().stdout}")
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Plug missing cache device."):
        cache_disk.plug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_device)
        TestRun.LOGGER.info(f"Dirty blocks on cache: "
                            f"{cache.get_dirty_blocks().get_value(Unit.Blocks4096)}")

    with TestRun.step("Stop cache with data flush."):
        cache.stop()

    with TestRun.step("Copy file from core device and check md5sum."):
        copy_file(source=core_device.system_path, target=target_file.full_path,
                  size=test_file_size, direct="iflag")
        compare_files(source_file, target_file)

    with TestRun.step("Cleanup core device and remove test files."):
        target_file.remove()
        source_file.remove()
