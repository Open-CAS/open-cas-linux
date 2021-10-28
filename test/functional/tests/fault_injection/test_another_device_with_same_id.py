#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time

import pytest

from api.cas import cli, casadm
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache_1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache_2", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_another_cache_with_same_id():
    """
        title: Test for creating another cache device with the same ID.
        description: |
          Checking if adding another cache device and setting
          the same cache ID as the previous one fails.
        pass_criteria:
          - No additional cache device added.
    """
    with TestRun.step("Start cache with ID = 1"):
        cache_dev_1 = TestRun.disks["cache_1"]
        cache_dev_1.create_partitions([Size(2, Unit.GibiByte)])
        TestRun.executor.run_expect_success(
            cli.start_cmd(
                cache_dev_1.partitions[0].path, cache_id="1", force=True
            )
        )

    with TestRun.step("Try to start another cache with the same ID = 1"):
        cache_dev_2 = TestRun.disks["cache_2"]
        cache_dev_2.create_partitions([Size(2, Unit.GibiByte)])
        TestRun.executor.run_expect_fail(
            cli.start_cmd(
                cache_dev_2.partitions[0].path, cache_id="1", force=True
            )
        )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core_1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core_2", DiskTypeLowerThan("cache"))
def test_another_core_with_same_id():
    """
        title: Test for creating another core device with the same ID.
        description: |
          Checking if adding another core device and setting
          the same core ID as the previous one fails.
        pass_criteria:
          - No additional core device added.
    """
    with TestRun.step("Start cache device"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache = casadm.start_cache(cache_dev.partitions[0], force=True)

    with TestRun.step("Add core with ID = 1"):
        core_dev_1 = TestRun.disks["core_1"]
        core_dev_1.create_partitions([Size(1, Unit.GibiByte)])
        TestRun.executor.run_expect_success(
            cli.add_core_cmd(
                cache_id=f"{cache.cache_id}",
                core_dev=f"{core_dev_1.partitions[0].path}",
                core_id="1",
            )
        )

    with TestRun.step("Try to add another core with the same ID = 1"):
        core_dev_2 = TestRun.disks["core_2"]
        core_dev_2.create_partitions([Size(1, Unit.GibiByte)])
        TestRun.executor.run_expect_fail(
            cli.add_core_cmd(
                cache_id=f"{cache.cache_id}",
                core_dev=f"{core_dev_2.partitions[0].path}",
                core_id="1",
            )
        )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()
