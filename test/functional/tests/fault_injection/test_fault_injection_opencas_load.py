#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser, cli, cli_messages
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_no_flush_load_cache(cache_mode, filesystem):
    """
        title: Test to check that 'stop --no-data-flush' command works correctly.
        description: |
          Negative test of the ability of CAS to load unflushed cache on core device
          with filesystem. Test uses lazy flush cache modes.
        pass_criteria:
          - No system crash while load cache.
          - Starting cache without loading metadata fails.
          - Starting cache with loading metadata finishes with success.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_part, core_part = prepare()

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step("Change cleaning policy to NOP."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step(f"Add core with {filesystem.name} filesystem to cache and mount it."):
        core_part.create_filesystem(filesystem)
        core = cache.add_core(core_part)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in mount point of exported object and check its md5 sum."):
        test_file = fs_utils.create_random_test_file(test_file_path, Size(48, Unit.MebiByte))
        test_file_md5_before = test_file.md5sum()

    with TestRun.step("Unmount exported object."):
        core.unmount()

    with TestRun.step("Count dirty blocks on exported object."):
        dirty_blocks_before = core.get_dirty_blocks()

    with TestRun.step("Stop cache with option '--no-data-flush'."):
        cache.stop(no_data_flush=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Try to start cache without loading metadata."):
        output = TestRun.executor.run_expect_fail(cli.start_cmd(
            cache_dev=str(cache_part.path), cache_mode=str(cache_mode.name.lower()),
            force=False, load=False))
        cli_messages.check_stderr_msg(output, cli_messages.start_cache_with_existing_metadata)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1 Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Compare dirty blocks number before and after loading cache."):
        if dirty_blocks_before != core.get_dirty_blocks():
            TestRun.LOGGER.error("Dirty blocks number is different than before loading cache.")

    with TestRun.step("Mount exported object."):
        core.mount(mount_point)

    with TestRun.step("Compare md5 sum of test file before and after loading cache."):
        if test_file_md5_before != test_file.md5sum():
            TestRun.LOGGER.error("Test file's md5 sum is different than before loading cache.")

    with TestRun.step("Unmount exported object."):
        core.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_no_flush_load_cache_no_fs(cache_mode):
    """
        title: Test to check that 'stop --no-data-flush' command works correctly.
        description: |
          Negative test of the ability of CAS to load unflushed cache on core device
          without filesystem. Test uses lazy flush cache modes.
        pass_criteria:
          - No system crash while load cache.
          - Starting cache without loading metadata fails.
          - Starting cache with loading metadata finishes with success.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_part, core_part = prepare()

    with TestRun.step("Start cache with --force option."):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step("Change cleaning policy to NOP."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Add core device without filesystem."):
        core_part.wipe_filesystem()
        core = cache.add_core(core_part)

    with TestRun.step("Fill exported object with data."):
        dd = (Dd()
              .input("/dev/zero")
              .output(core.path)
              .block_size(Size(1, Unit.Blocks4096))
              .oflag("direct"))
        dd.run()

    with TestRun.step("Count dirty blocks on exported object."):
        dirty_blocks_before = core.get_dirty_blocks()

    with TestRun.step("Stop cache with option '--no-data-flush'."):
        cache.stop(no_data_flush=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Try to start cache without loading metadata."):
        output = TestRun.executor.run_expect_fail(cli.start_cmd(
            cache_dev=str(cache_part.path), cache_mode=str(cache_mode.name.lower()),
            force=False, load=False))
        cli_messages.check_stderr_msg(output, cli_messages.start_cache_with_existing_metadata)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1 Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 1:
            TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Compare dirty blocks number before and after loading cache."):
        if dirty_blocks_before != core.get_dirty_blocks():
            TestRun.LOGGER.error("Dirty blocks number is different than before loading cache.")

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


def prepare():
    cache_dev = TestRun.disks['cache']
    cache_dev.create_partitions([Size(1, Unit.GibiByte)])
    cache_part = cache_dev.partitions[0]
    core_dev = TestRun.disks['core']
    core_dev.create_partitions([Size(2, Unit.GibiByte)])
    core_part = core_dev.partitions[0]
    os_utils.Udev.disable()
    return cache_part, core_part
