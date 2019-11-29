#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.dd import Dd
from test_utils.os_utils import wait
from test_utils.size import Size, Unit


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_multilevel_cas(cache_mode):
    """
        title: Test if OpenCAS not allow remove the core on 1 level cache when it's used by level 2.
        description: |
          False positive test of the ability to remove core used by nested OpenCAS.
        pass_criteria:
          - No system crash.
          - OpenCAS not allow remove the core on 1 level cache when is used by level 2.
    """
    with TestRun.step("Prepare two caches and one core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte), Size(2, Unit.GibiByte)])
        cache_dev1 = cache_dev.partitions[0]
        cache_dev2 = cache_dev.partitions[1]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start first OpenCAS"):
        cache1 = casadm.start_cache(cache_dev1, cache_mode, force=True)

    with TestRun.step("Add core device to first OpenCAS."):
        core1 = cache1.add_core(core_dev)

    with TestRun.step("Start second OpenCAS"):
        cache2 = casadm.start_cache(cache_dev2, cache_mode, force=True)

    with TestRun.step("Add openCAS device as a core to second OpenCAS."):
        cache2.add_core(core1)

    with TestRun.step("Try to remove core from 1st level cache."):
        try:
            cache1.remove_core(1, 1)
        except Exception:
            TestRun.LOGGER.info("Can't remove core as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 2:
                TestRun.fail(f"Expected caches count: 2; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache1.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")
            cores_count = len(casadm_parser.get_cores(cache2.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_one_core_remove():
    """
        title: Test if OpenCAS correctly handles the remove of one of the core devices.
        description: |
          When one core device is removed from a cache instance all blocks previously occupied
          by data from that core device should be removed. That means that number of free
          cache blocks should increase by number of removed blocks.
        pass_criteria:
          - No system crash.
          - Second core is able to use OpenCAS.
    """
    with TestRun.step("Prepare two caches and one core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte), Size(4, Unit.GibiByte)])
        core_dev1 = core_dev.partitions[0]
        core_dev2 = core_dev.partitions[1]

    with TestRun.step("Start OpenCAS"):
        cache = casadm.start_cache(cache_dev, CacheMode.WA, force=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Add first core device to OpenCAS."):
        cache.add_core(core_dev1)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Add second core device to OpenCAS."):
        cache.add_core(core_dev2)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 2:
            TestRun.fail(f"Expected cores count: 2; Actual cores count: {cores_count}.")

    with TestRun.step("Fill cache with pages from first core."):
        dd = (Dd()
              .input(f"{core_dev1.system_path}")
              .output("/dev/null")
              .block_size(Size(512, Unit.Byte)))
        dd.run()

    with TestRun.step("Remove first core."):
        cache.remove_core(1, 1)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Check if second core is able to use OpenCAS."):
        try:
            dd = (Dd()
                  .input(f"{core_dev2.system_path}")
                  .output("/dev/null")
                  .block_size(Size(512, Unit.Byte)))
            dd.run()
            cache.flush_cache()
            dd = (Dd()
                  .input(f"{core_dev2.system_path}")
                  .output("/dev/null")
                  .block_size(Size(512, Unit.Byte)))
            dd.run()
        except Exception:
            TestRun.fail("Second core is not able to use OpenCAS.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_one_core_release():
    """
        title: Test if OpenCAS correctly handles the release of one of the core devices.
        description: |
          When one core device is unused in a cache instance all blocks previously occupied
          by data from that core device should be removed. That means that number of free
          cache blocks should increase by number of released blocks.
        pass_criteria:
          - No system crash.
          - Second core is able to use OpenCAS.
    """
    with TestRun.step("Prepare two caches and one core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte), Size(4, Unit.GibiByte)])
        core_dev1 = core_dev.partitions[0]
        core_dev2 = core_dev.partitions[1]

    with TestRun.step("Start OpenCAS"):
        cache = casadm.start_cache(cache_dev, CacheMode.WA, force=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Add first core device to OpenCAS."):
        cache.add_core(core_dev1)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Add second core device to OpenCAS."):
        cache.add_core(core_dev2)
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 2:
            TestRun.fail(f"Expected cores count: 2; Actual cores count: {cores_count}.")

    with TestRun.step("Fill cache with pages from first core."):
        dd = (Dd()
              .input(f"{core_dev1.system_path}")
              .output("/dev/null")
              .block_size(Size(512, Unit.Byte)))
        dd.run()

    with TestRun.step("Check if second core is able to use OpenCAS."):
        try:
            dd = (Dd()
                  .input(f"{core_dev2.system_path}")
                  .output("/dev/null")
                  .block_size(Size(512, Unit.Byte)))
            dd.run()
            cache.flush_cache()
            dd = (Dd()
                  .input(f"{core_dev2.system_path}")
                  .output("/dev/null")
                  .block_size(Size(512, Unit.Byte)))
            dd.run()
        except Exception:
            TestRun.fail("Second core is not able to use OpenCAS.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()
