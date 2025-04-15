#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait, CleaningPolicy, SeqCutOffPolicy
from api.cas.cli import stop_cmd
from core.test_run import TestRun
from storage_devices.device import Device
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_tools.fs_tools import Filesystem
from test_utils.filesystem.file import File
from test_tools.os_tools import sync, drop_caches, DropCachesMode
from test_tools.udev import Udev
from type_def.size import Size, Unit

file_size = Size(640, Unit.GiB)
required_disk_size = file_size * 1.02


@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("separate_dev", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_flush_over_640_gibibytes_with_fs(cache_mode: CacheMode, filesystem: Filesystem):
    """
    title: Test of the ability to flush huge amount of dirty data on device with filesystem.
    description: |
        Flush cache when amount of dirty data in cache with core with filesystem exceeds 640 GiB.
    pass_criteria:
      - Flushing completes successfully without any errors.
    """
    exported_object_mount_point_path = "/mnt/flush_640G_test"
    separate_device_mount_point_path = "/mnt/cas/"

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]
        separate_dev = TestRun.disks["separate_dev"]

        check_disk_size(separate_dev)
        check_disk_size(cache_dev)
        check_disk_size(core_dev)

        cache_dev.create_partitions([required_disk_size])

        cache_part = cache_dev.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Drop caches"):
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step(f"Start cache in {cache_mode} mode"):
        cache = casadm.start_cache(cache_dev=cache_part, cache_mode=cache_mode)

    with TestRun.step(f"Create {filesystem.name} filesystem on core disk"):
        core_dev.create_filesystem(fs_type=filesystem)

    with TestRun.step("Add core with filesystem"):
        core = cache.add_core(core_dev=core_dev)

    with TestRun.step("Mount exported object"):
        core.mount(mount_point=separate_device_mount_point_path)

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(cleaning_policy=CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(policy=SeqCutOffPolicy.never)

    with TestRun.step(f"Create {filesystem.name} filesystem on separate disk"):
        separate_dev.create_filesystem(fs_type=filesystem)

    with TestRun.step("Mount separate disk"):
        separate_dev.mount(mount_point=exported_object_mount_point_path)

    with TestRun.step("Create a test file on a separate disk"):
        test_file_main = File.create_file(path=f"{exported_object_mount_point_path}/test_file_main")

    with TestRun.step("Run I/O to separate disk test file"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.write)
            .block_size(Size(2, Unit.MebiByte))
            .direct()
            .io_depth(256)
            .target(test_file_main.full_path)
            .size(file_size)
        )
        fio.default_run_time = timedelta(hours=4)  # timeout for non-time-based fio

        fio.run()

    with TestRun.step("Validate test file and read its checksum"):
        test_file_main.refresh_item()

        if test_file_main.size != file_size:
            TestRun.LOGGER.error(
                f"Expected test file size: {file_size}.\n"
                f"Actual test file size: {test_file_main.size}"
            )

        test_file_crc32sum_main = test_file_main.crc32sum(timeout=timedelta(hours=4))

    with TestRun.step("Write data to exported object"):
        test_file_copy = test_file_main.copy(
            separate_device_mount_point_path + "test_file_copy", timeout=timedelta(hours=4)
        )
        test_file_copy.refresh_item()
        sync()

    with TestRun.step(f"Check if dirty data exceeded {file_size * 0.98} GiB"):
        minimum_4KiB_blocks = int((file_size * 0.98).get_value(Unit.Blocks4096))
        actual_dirty_blocks = int(cache.get_statistics().usage_stats.dirty)

        if actual_dirty_blocks < minimum_4KiB_blocks:
            TestRun.LOGGER.error(
                f"Expected at least: {minimum_4KiB_blocks} dirty blocks.\n"
                f"Actual dirty blocks: {actual_dirty_blocks}"
            )

    with TestRun.step("Unmount core and stop cache with flush"):
        core.unmount()

        # this operation could take a few hours, depending on the core disk
        output = TestRun.executor.run(stop_cmd(str(cache.cache_id)), timedelta(hours=12))
        if output.exit_code != 0:
            TestRun.fail(f"Stopping cache with flush failed!\n{output.stderr}")

    with TestRun.step("Mount core device and check crc32 sum of test file copy"):
        core_dev.mount(separate_device_mount_point_path)

        if test_file_crc32sum_main != test_file_copy.crc32sum(timeout=timedelta(hours=4)):
            TestRun.fail("Crc32 sums should be equal.")


@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_flush_over_640_gibibytes_raw_device(cache_mode):
    """
    title: Test of the ability to flush huge amount of dirty data on raw device.
    description: |
        Flush cache when amount of dirty data in cache exceeds 640 GiB.
    pass_criteria:
      - Flushing completes successfully without any errors.
    """

    with TestRun.step("Prepare devices for cache and core"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        check_disk_size(cache_dev)
        check_disk_size(core_dev)

        cache_dev.create_partitions([required_disk_size])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} mode"):
        cache = casadm.start_cache(cache_dev=cache_part, cache_mode=cache_mode)

    with TestRun.step("Add core to cache"):
        core = cache.add_core(core_dev=core_dev)

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(cleaning_policy=CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(policy=SeqCutOffPolicy.never)

    with TestRun.step("Run I/O to separate disk test file"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.write)
            .block_size(Size(2, Unit.MebiByte))
            .direct()
            .io_depth(256)
            .target(core)
            .size(file_size)
        )
        fio.default_run_time = timedelta(hours=4)  # timeout for non-time-based fio

        fio.run()

    with TestRun.step(f"Check if dirty data exceeded {file_size * 0.98} GiB."):
        minimum_4KiB_blocks = int((file_size * 0.98).get_value(Unit.Blocks4096))
        if int(cache.get_statistics().usage_stats.dirty) < minimum_4KiB_blocks:
            TestRun.fail("There is not enough dirty data in the cache!")

    with TestRun.step("Stop cache with flush."):
        # this operation could take few hours, depending on core disk
        output = TestRun.executor.run(stop_cmd(str(cache.cache_id)), timedelta(hours=12))
        if output.exit_code != 0:
            TestRun.fail(f"Stopping cache with flush failed!\n{output.stderr}")


def check_disk_size(device: Device):
    if device.size < required_disk_size:
        pytest.skip(f"Not enough space on device {device.path}.")
