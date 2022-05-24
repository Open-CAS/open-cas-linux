#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from api.cas.casadm_parser import wait_for_flushing
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.os_utils import Udev, DropCachesMode
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"
iterations_per_config = 10
cache_size = Size(16, Unit.GibiByte)


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
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
          - Dirty blocks quantity after interruption is equal or lower but non-zero.
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

        with TestRun.step("Interrupt core flushing."):
            wait_for_flushing(cache, core)
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


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
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
          - Dirty blocks quantity after interruption is equal or lower but non-zero.
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

        with TestRun.step("Interrupt cache flushing"):
            wait_for_flushing(cache, core)
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


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_core_remove(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after core's removing interruption.
        description: |
          Negative test of the ability of OpenCAS to handle core's removing interruption.
        pass_criteria:
          - No system crash.
          - Core would not be removed from cache after interruption.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is lower but non-zero.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([cache_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([cache_size * 2])
        core_part = core_dev.partitions[0]

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

        with TestRun.step(
                "Get number of dirty data on exported object before core removal interruption."):
            os_utils.sync()
            os_utils.drop_caches(DropCachesMode.ALL)
            cache_dirty_blocks_before = cache.get_dirty_blocks()

        with TestRun.step("Unmount core."):
            core.unmount()

        with TestRun.step("Start removing core device."):
            flush_pid = TestRun.executor.run_in_background(
                cli.remove_core_cmd(str(cache.cache_id), str(core.core_id)))

        with TestRun.step("Interrupt core removing"):
            wait_for_flushing(cache, core)
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            while percentage < 50:
                percentage = casadm_parser.get_flushing_progress(cache.cache_i, core.core_id)
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step(
                "Check number of dirty data on exported object after core removal interruption."):
            cache_dirty_blocks_after = cache.get_dirty_blocks()
            if cache_dirty_blocks_after >= cache_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after core removal interruption "
                                     "should be lower.")
            if int(cache_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after core removal interruption "
                                     "should not be zero.")

        with TestRun.step("Remove core from cache."):
            core.remove_core()

        with TestRun.step("Stop cache."):
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error(
                    "Md5 sums before and after interrupting core removal are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_cache_mode_switch_immediately(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after cache mode switching immediate interruption.
        description: |
          Negative test of the ability of OpenCAS to handle cache mode switching
          immediate interruption.
        pass_criteria:
          - No system crash.
          - Cache mode will not be switched after interruption.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is lower but non-zero.
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

        with TestRun.step("Start switching cache mode."):
            flush_pid = TestRun.executor.run_in_background(cli.set_cache_mode_cmd(
                str(CacheMode.DEFAULT.name.lower()), str(cache.cache_id), "yes"))
            wait_for_flushing(cache, core)

        with TestRun.step("Send interruption signal."):
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step("Check number of dirty data on exported object after interruption."):
            cache_dirty_blocks_after = cache.get_dirty_blocks()
            if cache_dirty_blocks_after >= cache_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after cache mode switching "
                                     "interruption should be lower.")
            if int(cache_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after cache mode switching "
                                     "interruption should not be zero.")

        with TestRun.step("Check cache mode."):
            if cache.get_cache_mode() != cache_mode:
                TestRun.LOGGER.error("Cache mode should remain the same.")

        with TestRun.step("Unmount core and stop cache."):
            core.unmount()
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error(
                    "Md5 sums before and after interrupting mode switching are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_cache_mode_switch_delayed(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after cache mode switching delayed interruption.
        description: |
          Negative test of the ability of OpenCAS to handle cache mode switching
           interruption with delay.
        pass_criteria:
          - No system crash.
          - Cache mode will not be switched after interruption.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is lower but non-zero.
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

        with TestRun.step("Get number of dirty data on exported object before "
                          "switching cache mode interruption."):
            os_utils.sync()
            os_utils.drop_caches(DropCachesMode.ALL)
            cache_dirty_blocks_before = cache.get_dirty_blocks()

        with TestRun.step("Start switching cache mode."):
            flush_pid = TestRun.executor.run_in_background(cli.set_cache_mode_cmd(
                str(CacheMode.DEFAULT.name.lower()), str(cache.cache_id), "yes"))

        with TestRun.step("Send interruption signal."):
            wait_for_flushing(cache, core)
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            while percentage < 50:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step(
                "Get quantity of dirty data on exported object after sending interruption "
                "signal to cas to stop mode switching."):
            cache_dirty_blocks_after = cache.get_dirty_blocks()
            if cache_dirty_blocks_after >= cache_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after cache mode switching "
                                     "interruption should be lower.")
            if int(cache_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after cache mode switching "
                                     "interruption should not be zero.")

        with TestRun.step("Check cache mode."):
            if cache.get_cache_mode() != cache_mode:
                TestRun.LOGGER.error("Cache mode should remain the same.")

        with TestRun.step("Unmount core and stop cache."):
            core.unmount()
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error(
                    "Md5 sums before and after interrupting mode switching are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_interrupt_cache_stop(cache_mode, filesystem):
    """
        title: Test if OpenCAS works correctly after cache stopping interruption.
        description: |
          Negative test of the ability of OpenCAS to handle cache's stop interruption.
        pass_criteria:
          - No system crash.
          - Flushing would be stopped after interruption.
          - Md5sum are correct during all test steps.
          - Dirty blocks quantity after interruption is lower but non-zero.
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

        with TestRun.step("Unmount core."):
            core.unmount()

        with TestRun.step("Start stopping cache."):
            flush_pid = TestRun.executor.run_in_background(cli.stop_cmd(str(cache.cache_id)))

        with TestRun.step("Interrupt cache stopping."):
            wait_for_flushing(cache, core)
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            while percentage < 50:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core.core_id)
            TestRun.executor.run(f"kill -s SIGINT {flush_pid}")

        with TestRun.step("Check number of dirty data on exported object after interruption."):
            cache_dirty_blocks_after = cache.get_dirty_blocks()
            if cache_dirty_blocks_after >= cache_dirty_blocks_before:
                TestRun.LOGGER.error("Quantity of dirty lines after cache stop interruption "
                                     "should be lower.")
            if int(cache_dirty_blocks_after) == 0:
                TestRun.LOGGER.error("Quantity of dirty lines after cache stop interruption "
                                     "should not be zero.")

        with TestRun.step("Stop cache."):
            cache.stop()

        with TestRun.step("Mount core device."):
            core_part.mount(mount_point)

        with TestRun.step("Check md5 sum of test file again."):
            if test_file_md5sum_before != test_file.md5sum():
                TestRun.LOGGER.error("Md5 sums before and after interrupting"
                                     " cache stop are different.")

        with TestRun.step("Unmount core device."):
            core_part.unmount()


def prepare():
    cache_dev = TestRun.disks['cache']
    cache_dev.create_partitions([cache_size])
    cache_part = cache_dev.partitions[0]
    core_dev = TestRun.disks['core']
    core_dev.create_partitions([cache_size * 2])
    core_part = core_dev.partitions[0]
    Udev.disable()
    return cache_part, core_part


def create_test_file():
    from test_utils.filesystem.file import File
    from test_tools.dd import Dd
    bs = Size(512, Unit.KibiByte)
    cnt = int(cache_size.value / bs.value)
    test_file = File.create_file(test_file_path)
    dd = Dd().output(test_file_path) \
        .input("/dev/zero") \
        .block_size(bs) \
        .count(cnt)
    dd.run()
    test_file.refresh_item()
    return test_file
