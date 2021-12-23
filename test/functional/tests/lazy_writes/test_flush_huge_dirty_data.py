#
# Copyright(c) 2020-2021 Intel Corporation
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
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_tools.fs_utils import remove
from test_utils.filesystem.file import File
from test_utils.os_utils import sync, Udev
from test_utils.size import Size, Unit

file_size = Size(640, Unit.GiB)
required_disk_size = file_size * 1.02
bs = Size(64, Unit.MebiByte)
mnt_point = "/mnt/cas/"


@pytest.mark.parametrizex("fs", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_flush_over_640_gibibytes_with_fs(cache_mode, fs):
    """
        title: Test of the ability to flush huge amount of dirty data on device with filesystem.
        description: |
          Flush cache when amount of dirty data in cache with core with filesystem exceeds 640 GiB.
        pass_criteria:
          - Flushing completes successfully without any errors.
    """
    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks['cache']
        check_disk_size(cache_dev)
        cache_dev.create_partitions([required_disk_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        check_disk_size(core_dev)
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} mode."):
        cache = casadm.start_cache(cache_part, cache_mode)

    with TestRun.step(f"Add core with {fs.name} filesystem to cache and mount it."):
        core_dev.create_filesystem(fs)
        core = cache.add_core(core_dev)
        core.mount(mnt_point)

    with TestRun.step("Disable cleaning and sequential cutoff."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Create test file"):
        test_file_main = File.create_file("/tmp/test_file_main")
        fio = (
            Fio().create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.write)
            .block_size(bs)
            .direct()
            .io_depth(256)
            .target(test_file_main.full_path)
            .size(file_size)
        )
        fio.default_run_time = timedelta(hours=4)  # timeout for non-time-based fio
        fio.run()
        test_file_main.refresh_item()

    with TestRun.step("Validate test file and read its md5 sum."):
        if test_file_main.size != file_size:
            TestRun.fail("Created test file hasn't reached its target size.")
        test_file_md5sum_main = test_file_main.md5sum()

    with TestRun.step("Write data to exported object."):
        test_file_copy = test_file_main.copy(mnt_point + "test_file_copy")
        test_file_copy.refresh_item()
        sync()

    with TestRun.step(f"Check if dirty data exceeded {file_size * 0.98} GiB."):
        minimum_4KiB_blocks = int((file_size * 0.98).get_value(Unit.Blocks4096))
        if int(cache.get_statistics().usage_stats.dirty) < minimum_4KiB_blocks:
            TestRun.fail("There is not enough dirty data in the cache!")

    with TestRun.step("Unmount core and stop cache with flush."):
        core.unmount()
        # this operation could take few hours, depending on core disk
        output = TestRun.executor.run(stop_cmd(str(cache.cache_id)), timedelta(hours=12))
        if output.exit_code != 0:
            TestRun.fail(f"Stopping cache with flush failed!\n{output.stderr}")

    with TestRun.step("Mount core device and check md5 sum of test file copy."):
        core_dev.mount(mnt_point)
        if test_file_md5sum_main != test_file_copy.md5sum():
            TestRun.LOGGER.error("Md5 sums should be equal.")

    with TestRun.step("Delete test files."):
        test_file_main.remove(True)
        test_file_copy.remove(True)

    with TestRun.step("Unmount core device."):
        core_dev.unmount()
        remove(mnt_point, True, True, True)


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
    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks['cache']
        check_disk_size(cache_dev)
        cache_dev.create_partitions([required_disk_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        check_disk_size(core_dev)
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} mode."):
        cache = casadm.start_cache(cache_part, cache_mode)

    with TestRun.step(f"Add core to cache."):
        core = cache.add_core(core_dev)

    with TestRun.step("Disable cleaning and sequential cutoff."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Create test file"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.write)
            .block_size(bs)
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
