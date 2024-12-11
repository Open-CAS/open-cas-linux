#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

import test_tools.udev
from api.cas import casadm, casadm_parser, cli, cli_messages
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from tests.lazy_writes.recovery.recovery_tests_methods import copy_file, compare_files
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from type_def.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_no_flush_load_cache(cache_mode):
    """
        title: Test to check that 'stop --no-data-flush' command works correctly.
        description: |
          Negative test of the ability of CAS to load unflushed cache on core device.
          Test uses lazy flush cache modes.
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

    with TestRun.step("Add core to cache."):
        core = cache.add_core(core_part)

    with TestRun.step(f"Create test file in mount point of exported object and check its md5 sum."):
        test_file_size = Size(48, Unit.MebiByte)
        test_file = fs_utils.create_random_test_file(test_file_path, test_file_size)
        test_file_md5_before = test_file.md5sum()
        copy_file(source=test_file.full_path, target=core.path, size=test_file_size,
                  direct="oflag")

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

    with TestRun.step("Compare md5 sum of test file before and after loading cache."):
        copy_file(source=core.path, target=test_file.full_path,
                  size=test_file_size, direct="iflag")
        target_file_md5 = test_file.md5sum()
        compare_files(test_file_md5_before, target_file_md5)

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


def prepare():
    cache_dev = TestRun.disks['cache']
    cache_dev.create_partitions([Size(1, Unit.GibiByte)])
    cache_part = cache_dev.partitions[0]
    core_dev = TestRun.disks['core']
    core_dev.create_partitions([Size(2, Unit.GibiByte)])
    core_part = core_dev.partitions[0]
    test_tools.udev.Udev.disable()
    return cache_part, core_part
