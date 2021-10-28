#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser, cli, cli_messages
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_cache_with_mounted_core(cache_mode):
    """
        title: Fault injection test for adding mounted core on cache load.
        description: |
          Negative test of the ability of CAS to add to cache while its loading
          core device which is mounted.
        pass_criteria:
          - No system crash while loading cache.
          - Adding mounted core while loading cache fails.
    """
    with TestRun.step("Prepare cache and core devices. Start CAS."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step("Add core device with xfs filesystem to cache and mount it."):
        core_part.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_part)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in mount point of exported object and check its md5 sum."):
        test_file = fs_utils.create_random_test_file(test_file_path)
        test_file_md5_before = test_file.md5sum()

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Mount core device."):
        core_part.mount(mount_point)

    with TestRun.step("Try to load cache."):
        cache = casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1 Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 0:
            TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")

    with TestRun.step("Check md5 sum of test file again."):
        if test_file_md5_before != test_file.md5sum():
            TestRun.LOGGER.error("Md5 sum of test file is different.")
        core_part.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_cache_with_mounted_partition(cache_mode):
    """
        title: Fault injection test for removing core and stopping cache with mounted core.
        description: |
          Negative test of the ability of CAS to remove core and stop cache while core
          is still mounted.
        pass_criteria:
          - No system crash.
          - Unable to stop cache when partition is mounted.
          - Unable to remove core when partition is mounted.
    """
    with TestRun.step("Prepare cache and core devices. Start CAS."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step("Add core device with xfs filesystem and mount it."):
        core_part.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_part)
        core.mount(mount_point)

    with TestRun.step("Try to remove core from cache."):
        output = TestRun.executor.run_expect_fail(cli.remove_core_cmd(cache_id=str(cache.cache_id),
                                                                      core_id=str(core.core_id)))
        cli_messages.check_stderr_msg(output, cli_messages.remove_mounted_core)

    with TestRun.step("Try to stop CAS."):
        output = TestRun.executor.run_expect_fail(cli.stop_cmd(cache_id=str(cache.cache_id)))
        cli_messages.check_stderr_msg(output, cli_messages.stop_cache_mounted_core)

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_cached_core(cache_mode):
    """
        title: Fault injection test for adding already used core to a cache.
        description: |
          Negative test of the ability to add the core to the cache twice to the same cache
          and while the core is already used by the another cache instance.
        pass_criteria:
          - No system crash.
          - Adding already used core to another cache instance fails.
          - The same core device cannot be used twice in one cache instance.
    """
    with TestRun.step("Prepare two caches and one core device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte), Size(2, Unit.GibiByte)])
        cache_part1 = cache_dev.partitions[0]
        cache_part2 = cache_dev.partitions[1]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start the first cache instance"):
        cache1 = casadm.start_cache(cache_part1, cache_mode, force=True)

    with TestRun.step("Add core device to first cache instance."):
        core = cache1.add_core(core_part)

    with TestRun.step("Start the second cache instance"):
        cache2 = casadm.start_cache(cache_part2, cache_mode, force=True)

    with TestRun.step("Try adding the same core device to the second cache instance."):
        output = TestRun.executor.run_expect_fail(
            cli.add_core_cmd(cache_id=str(cache2.cache_id), core_dev=str(core_part.path),
                             core_id=str(core.core_id)))
        cli_messages.check_stderr_msg(output, cli_messages.add_cached_core)

    with TestRun.step("Try adding the same core device to the same cache for the second time."):
        output = TestRun.executor.run_expect_fail(
            cli.add_core_cmd(cache_id=str(cache1.cache_id), core_dev=str(core_part.path)))
        cli_messages.check_stderr_msg(output, cli_messages.already_cached_core)

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()
