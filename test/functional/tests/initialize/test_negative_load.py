#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest
from api.cas import casadm, casadm_parser, cli, cli_messages
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from types.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_occupied_id():
    """
    title: Negative test for loading cache with occupied ID.
    description: |
      Verify that loading cache with occupied ID is not permitted.
    pass_criteria:
      - Loading cache with occupied ID should fail.
    """

    with TestRun.step("Create partitions for test."):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions([Size(500, Unit.MebiByte), Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        cache_device_1 = cache_device.partitions[0]
        cache_device_2 = cache_device.partitions[1]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache with default id and one core."):
        cache1 = casadm.start_cache(cache_device_1, force=True)
        cache1.add_core(core_device)

    with TestRun.step("Stop cache."):
        cache1.stop()

    with TestRun.step("Start cache with default id on different device."):
        casadm.start_cache(cache_device_2, force=True)

    with TestRun.step("Attempt to load metadata from first cache device."):
        try:
            casadm.load_cache(cache_device_1)
            TestRun.fail("Cache loaded successfully but it should not.")
        except Exception:
            pass

        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.LOGGER.error("Inappropriate number of caches after load!")
        if caches[0].cache_device.path != cache_device_2.path:
            TestRun.LOGGER.error("Wrong cache device system path!")
        if caches[0].cache_id != 1:
            TestRun.LOGGER.error("Wrong cache id.")

        cores = caches[0].get_core_devices()
        if len(cores) != 0:
            TestRun.LOGGER.error("Inappropriate number of cores after load!")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_cached_core():
    """
    title: Negative test for adding already used core to a cache.
    description: |
        Verify if adding core to cache instance fails while it is already
        added to another instance and verify if it fails when trying to add core
        again to cache where its added already.
    pass_criteria:
      - No system crash.
      - Adding already used core to another cache instance fails.
      - The same core device cannot be used twice in one cache instance.
    """
    with TestRun.step("Prepare two caches and one core device."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte), Size(2, Unit.GibiByte)])
        cache_part1 = cache_dev.partitions[0]
        cache_part2 = cache_dev.partitions[1]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start the first cache instance"):
        cache1 = casadm.start_cache(cache_part1, force=True)

    with TestRun.step("Add core device to first cache instance."):
        core = cache1.add_core(core_part)

    with TestRun.step("Start the second cache instance"):
        cache2 = casadm.start_cache(cache_part2, force=True)

    with TestRun.step("Try adding the same core device to the second cache instance."):
        output = TestRun.executor.run_expect_fail(
            cli.add_core_cmd(
                cache_id=str(cache2.cache_id),
                core_dev=str(core_part.path),
                core_id=str(core.core_id),
            )
        )
        cli_messages.check_stderr_msg(output, cli_messages.add_cached_core)

    with TestRun.step("Try adding the same core device to the same cache for the second time."):
        output = TestRun.executor.run_expect_fail(
            cli.add_core_cmd(cache_id=str(cache1.cache_id), core_dev=str(core_part.path))
        )
        cli_messages.check_stderr_msg(output, cli_messages.already_cached_core)

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()
