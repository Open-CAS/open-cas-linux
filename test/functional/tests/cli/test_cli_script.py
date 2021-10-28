#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm, casadm_parser
from core.test_run import TestRun
from test_utils.os_utils import sync
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Unit, Size
from test_tools.dd import Dd


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("purge_target", ["cache", "core"])
def test_purge(purge_target):
    """
        title: Call purge without and with `--script` switch
        description: |
          Check if purge is called only when `--script` switch is used.
        pass_criteria:
          - casadm returns an error when `--script` is missing
          - cache is wiped when purge command is used properly
    """
    with TestRun.step("Prepare devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(500, Unit.MebiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Prepare cache instance"):
        cache = casadm.start_cache(cache_device, force=True)
        core = casadm.add_core(cache, core_device)

    with TestRun.step("Trigger IO to prepared cache instance"):
        dd = (
            Dd()
            .input("/dev/zero")
            .output(core.path)
            .count(100)
            .block_size(Size(1, Unit.Blocks512))
            .oflag("direct")
        )
        dd.run()
        sync()

    with TestRun.step(
        f"Try to call purge-{purge_target} without `--script` switch"
    ):
        original_occupancy = cache.get_statistics().usage_stats.occupancy
        purge_params = f"--cache-id {cache.cache_id} "
        if purge_target == "core":
            purge_params += f"--core-id {core.core_id}"
        TestRun.executor.run_expect_fail(
            f"casadm --purge-{purge_target} {purge_params}"
        )

        if cache.get_statistics().usage_stats.occupancy != original_occupancy:
            TestRun.fail(
                f"Purge {purge_target} should not be possible to use without `--script` switch!"
            )

    with TestRun.step(
        f"Try to call purge-{purge_target} with `--script` switch"
    ):
        TestRun.executor.run_expect_success(
            f"casadm --script --purge-{purge_target} {purge_params}"
        )

        if cache.get_statistics().usage_stats.occupancy.get_value() != 0:
            TestRun.fail(f"{cache.get_statistics().usage_stats.occupancy.get_value()}")
            TestRun.fail(f"Purge {purge_target} should invalidate all cache lines!")

    with TestRun.step(
        f"Stop cache"
    ):
        casadm.stop_all_caches()
