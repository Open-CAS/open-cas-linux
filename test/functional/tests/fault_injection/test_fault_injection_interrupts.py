#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
from time import sleep

import pytest

from api.cas import casadm, casadm_parser, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.os_utils import Udev, DropCachesMode
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"
iterations_per_config = 10
cache_size = Size(16, Unit.GibiByte)


@pytest.mark.parametrize("filesystem", Filesystem)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_core_flush(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after core's flushing interruption.
        description: |
          Negative test of the ability of OpenCAS to handle core flushing interruption.
        pass_criteria:
          - No system crash.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is equal or lower.
    """
    with TestRun.step("Prepare cache and core."):
        cache_part, core_part = prepare()

    for _ in TestRun.iteration(range(iterations_per_config),
                               f"Reload cache configuration {iterations_per_config} times."):

        with TestRun.step("Start cache."):
            cache = casadm.start_cache(cache_part, cache_mode, force=True)

        with TestRun.step("Set cleaning policy to NOP."):
            cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step(f"Add core device with {filesystem} filesystem and mount it."):
            core_part.create_filesystem(filesystem)
            core = cache.add_core(core_part)
            core.mount(mount_point)

        with TestRun.step(f"Create test file in mount point of exported object."):
            test_file = create_test_file()

        with TestRun.step("Check md5 sum of test file."):
            test_file_md5sum_before = test_file.md5sum()

        with TestRun.step("Get number of dirty data on exported object before interruption."):
            os_utils.sync()
            os_utils.drop_caches(DropCachesMode.ALL)
            core_dirty_blocks_before = core.get_dirty_blocks()

        with TestRun.step("Start flushing core device."):
            flush_pid = TestRun.executor.run_in_background(
                cli.flush_core_cmd(str(cache.cache_id), str(core.core_id)))
            sleep(2)

        with TestRun.step("Interrupt core flushing."):
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            while percentage < 50:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step("Check number of dirty data on exported object after interruption."):
            core_dirty_blocks_after = core.get_dirty_blocks()
            if core_dirty_blocks_after >= core_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after core flush interruption "
                                     "should be lower.")
            if int(core_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after core flush interruption "
                                     "should not be zero.")

        with TestRun.step("Unmount core and stop cache."):
            core.unmount()
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error(
                    "Md5 sums before and after interrupting core flush are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()


@pytest.mark.parametrize("filesystem", Filesystem)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_cache_flush(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after cache's flushing interruption.
        description: |
          Negative test of the ability of OpenCAS to handle cache flushing interruption.
        pass_criteria:
          - No system crash.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is equal or lower.
    """
    with TestRun.step("Prepare cache and core."):
        cache_part, core_part = prepare()

    for _ in TestRun.iteration(range(iterations_per_config),
                               f"Reload cache configuration {iterations_per_config} times."):

        with TestRun.step("Start cache."):
            cache = casadm.start_cache(cache_part, cache_mode, force=True)

        with TestRun.step("Set cleaning policy to NOP."):
            cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step(f"Add core device with {filesystem} filesystem and mount it."):
            core_part.create_filesystem(filesystem)
            core = cache.add_core(core_part)
            core.mount(mount_point)

        with TestRun.step(f"Create test file in mount point of exported object."):
            test_file = create_test_file()

        with TestRun.step("Check md5 sum of test file."):
            test_file_md5sum_before = test_file.md5sum()

        with TestRun.step("Get number of dirty data on exported object before interruption."):
            os_utils.sync()
            os_utils.drop_caches(DropCachesMode.ALL)
            cache_dirty_blocks_before = cache.get_dirty_blocks()

        with TestRun.step("Start flushing cache."):
            flush_pid = TestRun.executor.run_in_background(
                cli.flush_cache_cmd(str(cache.cache_id)))
            sleep(2)

        with TestRun.step("Interrupt cache flushing"):
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            while percentage < 50:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step("Check number of dirty data on exported object after interruption."):
            cache_dirty_blocks_after = cache.get_dirty_blocks()
            if cache_dirty_blocks_after >= cache_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after cache flush interruption "
                                     "should be lower.")
            if int(cache_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after cache flush interruption "
                                     "should not be zero.")

        with TestRun.step("Unmount core and stop cache."):
            core.unmount()
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error(
                    "Md5 sums before and after interrupting cache flush are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()

