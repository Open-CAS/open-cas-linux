#
# Copyright(c) 2023-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import random
import time
import pytest


from api.cas import casadm_parser, casadm
from api.cas.cache_config import CacheLineSize, CacheMode
from api.cas.cli import attach_cache_cmd
from api.cas.cli_messages import check_stderr_msg, attach_with_existing_metadata
from connection.utils.output import CmdException
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from storage_devices.nullblk import NullBlk
from test_tools.dmesg import clear_dmesg
from test_tools.fs_tools import Filesystem, create_directory, create_random_test_file, \
    check_if_directory_exists, remove
from type_def.size import Size, Unit

mountpoint = "/mnt/cas"
test_file_path = f"{mountpoint}/test_file"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_attach_device_with_existing_metadata(cache_mode, cache_line_size):
    """
    title: Test attaching cache with valid and relevant metadata.
    description: |
        Attach disk with valid and relevant metadata and verify whether the running configuration
        wasn't affected by the values from the old metadata.
    pass_criteria:
      - no cache crash during attach and detach.
      - old metadata doesn't affect running cache.
      - no kernel panic
    """

    with TestRun.step("Prepare random cache line size and cache mode (different than tested)"):
        random_cache_mode = _get_random_uniq_cache_mode(cache_mode)
        cache_mode1, cache_mode2 = cache_mode, random_cache_mode
        random_cache_line_size = _get_random_uniq_cache_line_size(cache_line_size)
        cache_line_size1, cache_line_size2 = cache_line_size, random_cache_line_size

    with TestRun.step("Clear dmesg log"):
        clear_dmesg()

    with TestRun.step("Prepare devices for caches and cores"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]

        cache_dev2 = TestRun.disks["cache2"]
        cache_dev2.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev2 = cache_dev2.partitions[0]

        core_dev1 = TestRun.disks["core"]
        core_dev2 = TestRun.disks["core2"]
        core_dev1.create_partitions([Size(2, Unit.GibiByte)] * 2)
        core_dev2.create_partitions([Size(2, Unit.GibiByte)] * 2)

    with TestRun.step("Start 2 caches with different parameters and add core to each"):
        cache1 = casadm.start_cache(
            cache_dev, force=True, cache_line_size=cache_line_size1
        )

        if cache1.has_volatile_metadata():
            pytest.skip("Non-volatile metadata needed to run this test")

        for core in core_dev1.partitions:
            cache1.add_core(core)

        cache2 = casadm.start_cache(
            cache_dev2, force=True, cache_line_size=cache_line_size2
        )

        for core in core_dev2.partitions:
            cache2.add_core(core)

        cores_in_cache1_before = {
            core.core_device.path for core in casadm_parser.get_cores(cache_id=cache1.cache_id)
        }

    with TestRun.step(f"Set cache modes for caches to {cache_mode1} and {cache_mode2}"):
        cache1.set_cache_mode(cache_mode1)
        cache2.set_cache_mode(cache_mode2)

    with TestRun.step("Stop second cache"):
        cache2.stop()

    with TestRun.step("Detach first cache device"):
        cache1.detach()

    with TestRun.step("Try to attach the other cache device to first cache without force flag"):
        try:
            cache1.attach(device=cache_dev2)
            TestRun.fail("Cache attached successfully"
                         "Expected: cache fail to attach")
        except CmdException as exc:
            check_stderr_msg(exc.output, attach_with_existing_metadata)
            TestRun.LOGGER.info("Cache attach failed as expected")

    with TestRun.step("Attach the other cache device to first cache with force flag"):
        cache1.attach(device=cache_dev2, force=True)
        cores_after_attach = casadm_parser.get_cores(cache_id=cache1.cache_id)

    with TestRun.step("Verify if old configuration doesn`t affect new cache"):
        cores_in_cache1 = {core.core_device.path for core in cores_after_attach}

        if cores_in_cache1 != cores_in_cache1_before:
            TestRun.fail(
                f"After attaching cache device, core list has changed:"
                f"\nUsed {cores_in_cache1}"
                f"\nShould use {cores_in_cache1_before}."
            )
        if cache1.get_cache_line_size() == cache_line_size2:
            TestRun.fail(
                f"After attaching cache device, cache line size changed:"
                f"\nUsed {cache_line_size2}"
                f"\nShould use {cache_line_size1}."
            )
        if cache1.get_cache_mode() != cache_mode1:
            TestRun.fail(
                f"After attaching cache device, cache mode changed:"
                f"\nUsed {cache1.get_cache_mode()}"
                f"\nShould use {cache_mode1}."
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", [CacheMode.WB, CacheMode.WT])
def test_attach_detach_md5sum(cache_mode):
    """
    title: Test for md5sum of file after attach/detach operation.
    description: |
        Test data integrity after detach/attach operations
    pass_criteria:
      - CAS doesn't crash during attach and detach.
      - md5sums before and after operations match each other
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]

        cache_dev2 = TestRun.disks["cache2"]
        cache_dev2.create_partitions([Size(3, Unit.GibiByte)])
        cache_dev2 = cache_dev2.partitions[0]

        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(6, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev, force=True, cache_mode=cache_mode)
        core = cache.add_core(core_dev)

    with TestRun.step(f"Change cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    with TestRun.step("Create a filesystem on the core device and mount it"):
        if check_if_directory_exists(mountpoint):
            remove(mountpoint, force=True, recursive=True)
        create_directory(path=mountpoint)
        core.create_filesystem(Filesystem.xfs)
        core.mount(mountpoint)

    with TestRun.step("Write data to the exported object"):
        test_file_main = create_random_test_file(
            target_file_path=posixpath.join(mountpoint, "test_file"),
            file_size=Size(5, Unit.GibiByte),
        )

    with TestRun.step("Calculate test file md5sums before detach"):
        test_file_md5sum_before = test_file_main.md5sum()

    with TestRun.step("Detach cache device"):
        cache.detach()

    with TestRun.step("Attach different cache device"):
        cache.attach(device=cache_dev2, force=True)

    with TestRun.step("Calculate cache test file md5sums after cache attach"):
        test_file_md5sum_after = test_file_main.md5sum()

    with TestRun.step("Compare test file md5sums"):
        if test_file_md5sum_before != test_file_md5sum_after:
            TestRun.fail(
                f"MD5 sums of core before and after do not match."
                f"Expected: {test_file_md5sum_before}"
                f"Actual: {test_file_md5sum_after}"
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_stop_cache_during_attach(cache_mode):
    """
    title: Test cache stop during attach.
    description: Test for handling concurrent cache attach and stop.
    pass_criteria:
      - No system crash.
      - Stop operation completed successfully.
    """

    with TestRun.step("Create null_blk device for cache"):
        nullblk = NullBlk.create(size_gb=1500)

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = nullblk[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev, force=True, cache_mode=cache_mode)
        cache.add_core(core_dev)

    with TestRun.step(f"Change cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Start cache re-attach in background"):
        TestRun.executor.run_in_background(
            attach_cache_cmd(str(cache.cache_id), cache_dev.path)
        )
        time.sleep(1)

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Verify if cache stopped"):
        caches = casadm_parser.get_caches()
        if caches:
            TestRun.fail(
                "Cache is still running despite stop operation"
                "expected behaviour: Cache stopped"
                "actual behaviour: Cache running"
            )


def _get_random_uniq_cache_line_size(cache_line_size) -> CacheLineSize:
    return random.choice([c for c in list(CacheLineSize) if c is not cache_line_size])


def _get_random_uniq_cache_mode(cache_mode) -> CacheMode:
    return random.choice([c for c in list(CacheMode) if c is not cache_mode])
