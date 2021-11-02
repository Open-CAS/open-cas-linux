#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode, SeqCutOffPolicy, CacheModeTrait
from api.cas.core import Core
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.dd import Dd
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit

block_size = Size(1, Unit.Blocks4096)


@pytest.mark.parametrize("cache_mode", CacheMode.with_any_trait(CacheModeTrait.InsertRead
                                                                | CacheModeTrait.InsertWrite))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_one_core_remove(cache_mode):
    """
        title: Test if OpenCAS correctly handles removal of one of multiple core devices.
        description: |
          When one core device is removed from a cache instance all blocks previously occupied
          by the data from that core device should be removed. That means that the number of free
          cache blocks should increase by the number of removed blocks.
          Test is without pass through mode.
        pass_criteria:
          - No system crash.
          - The remaining core is able to use cache.
          - Removing core frees cache blocks occupied by this core.
    """
    with TestRun.step("Prepare one device for cache and two for core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(512, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte)] * 2)
        core_part1 = core_dev.partitions[0]
        core_part2 = core_dev.partitions[1]
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Add both core devices to cache."):
        core1 = cache.add_core(core_part1)
        core2 = cache.add_core(core_part2)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 2:
            TestRun.fail(f"Expected cores count: 2; Actual cores count: {cores_count}.")

    with TestRun.step("Fill cache with pages from the first core."):
        dd_builder(cache_mode, core1, cache.size).run()
        core1_occupied_blocks = core1.get_occupancy()
        occupied_blocks_before = cache.get_occupancy()

    with TestRun.step("Remove the first core."):
        cache.remove_core(core1.core_id, True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Check if occupancy from the first core is removed from cache."):
        # Blocks occupied by the first core should be completely released.
        if cache.get_occupancy() != occupied_blocks_before - core1_occupied_blocks:
            TestRun.LOGGER.error("Blocks previously occupied by the first core "
                                 "aren't released by removing this core.")

    with TestRun.step("Check if the remaining core is able to use cache."):
        dd_builder(cache_mode, core2, Size(100, Unit.MebiByte)).run()
        if not float(core2.get_occupancy().get_value()) > 0:
            TestRun.fail("The remaining core is not able to use cache.")

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.parametrize("cache_mode", CacheMode.with_any_trait(CacheModeTrait.InsertRead
                                                                | CacheModeTrait.InsertWrite))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_one_core_release(cache_mode):
    """
        title: Test if OpenCAS dynamically allocates space according to core devices needs.
        description: |
          When one or more core devices are unused in a single cache instance all blocks
          previously occupied should be available to other core devices.
          Test is without pass through mode.
        pass_criteria:
          - No system crash.
          - The remaining core is able to use cache.
          - OpenCAS frees blocks occupied by unused core and allocates it to the remaining core.
    """
    with TestRun.step("Prepare two cache and one core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(512, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte)] * 2)
        core_part1 = core_dev.partitions[0]
        core_part2 = core_dev.partitions[1]
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Add both core devices to cache."):
        core1 = cache.add_core(core_part1)
        core2 = cache.add_core(core_part2)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 2:
            TestRun.fail(f"Expected cores count: 2; Actual cores count: {cores_count}.")

    with TestRun.step("Change sequential cutoff policy to 'never'."):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Fill cache with pages from the first core."):
        dd_builder(cache_mode, core1, cache.size).run()
        core1_occupied_blocks_before = core1.get_occupancy()

    with TestRun.step("Check if the remaining core is able to use cache."):
        dd_builder(cache_mode, core2, Size(100, Unit.MebiByte)).run()
        core1_occupied_blocks_after = core1.get_occupancy()

    with TestRun.step("Check if occupancy from the first core is removed from cache."):
        # The first core's occupancy should be lower than cache's occupancy
        # by the value of the remaining core's occupancy because cache
        # should reallocate blocks from unused core to used core.
        if core1_occupied_blocks_after >= core1_occupied_blocks_before \
                or cache.get_occupancy() <= core1_occupied_blocks_after \
                or not float(core2.get_occupancy().get_value()) > 0:
            TestRun.LOGGER.error("Blocks previously occupied by the first core aren't released.")

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.parametrize("cache_mode", CacheMode.with_any_trait(CacheModeTrait.InsertRead
                                                                | CacheModeTrait.InsertWrite))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
def test_one_core_fail(cache_mode):
    """
        title: Test if OpenCAS correctly handles failure of one of multiple core devices.
        description: |
          When one core device fails in a single cache instance all blocks previously occupied
          should be available to other core devices.
          Test is without pass through mode.
        pass_criteria:
          - No system crash.
          - Second core is able to use OpenCAS.
    """
    with TestRun.step("Prepare one cache and two core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)] * 2)
        cache_part = cache_dev.partitions[0]
        core_dev1 = TestRun.disks['core1']  # This device would be unplugged.
        core_dev1.create_partitions([Size(2, Unit.GibiByte)])
        core_part1 = core_dev1.partitions[0]
        core_dev2 = TestRun.disks['core2']
        core_dev2.create_partitions([Size(2, Unit.GibiByte)])
        core_part2 = core_dev2.partitions[0]
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Add both core devices to cache."):
        core1 = cache.add_core(core_part1)
        core2 = cache.add_core(core_part2)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 2:
            TestRun.fail(f"Expected cores count: 2; Actual cores count: {cores_count}.")

    with TestRun.step("Change sequential cutoff policy."):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Fill cache with pages from the first core."):
        dd_builder(cache_mode, core1, cache.size).run()
        cache_occupied_blocks_before = cache.get_occupancy()

    with TestRun.step("Unplug the first core device."):
        core_dev1.unplug()

    with TestRun.step("Check if core device is really out of cache."):
        output = str(casadm.list_caches().stdout.splitlines())
        if core_part1.path in output:
            TestRun.fail("The first core device should be unplugged!")

    with TestRun.step("Check if the remaining core is able to use cache."):
        dd_builder(cache_mode, core2, Size(100, Unit.MebiByte)).run()
        if not float(core2.get_occupancy().get_value()) > 0:
            TestRun.LOGGER.error("The remaining core is not able to use cache.")

    with TestRun.step("Check if occupancy from the first core is removed from cache."):
        # Cache occupancy cannot be lower than before the first core fails and after that
        # should be equal to the sum of occupancy of the first and the remaining core
        cache_occupied_blocks_after = cache.get_occupancy()
        if cache_occupied_blocks_before > cache_occupied_blocks_after \
                or cache_occupied_blocks_after != core2.get_occupancy() + core1.get_occupancy():
            TestRun.fail("Blocks previously occupied by the first core "
                         "aren't released after this core failure.")

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()

    with TestRun.step("Plug back the first core."):
        core_dev1.plug()


def dd_builder(cache_mode: CacheMode, dev: Core, size: Size):
    blocks = int(size.value / block_size.value)
    dd = (Dd()
          .block_size(block_size)
          .count(blocks))
    if CacheModeTrait.InsertRead in CacheMode.get_traits(cache_mode):
        dd.input(dev.path).output("/dev/null")
    else:
        dd.input("/dev/urandom").output(dev.path)
    return dd
