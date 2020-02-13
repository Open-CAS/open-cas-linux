#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
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

