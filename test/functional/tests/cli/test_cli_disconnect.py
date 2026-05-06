#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm
from api.cas.casadm_parser import get_caches
from api.cas.cli import script_disconnect_cache_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from type_def.size import Unit, Size


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_pt_and_no_flush():
    """
        title: Disconnect rejects --pass-through with --no-flush
        description: |
            Pass-through mode requires the cache to be flushed and purged on disconnect
            to avoid stale data on reconnect, so it cannot be combined with --no-flush.
        pass_criteria:
          - disconnect with --pass-through and --no-flush together is rejected
          - cache remains running afterwards
    """
    with TestRun.step("Prepare devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(500, Unit.MebiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_device, force=True)
        casadm.add_core(cache, core_device)

    with TestRun.step(
        "Try to disconnect with --pass-through and --no-flush at the same time"
    ):
        TestRun.executor.run_expect_fail(
            script_disconnect_cache_cmd(
                str(cache.cache_id), pass_through=True, no_flush=True
            )
        )

    with TestRun.step("Verify cache is still running"):
        if not any(c.cache_id == cache.cache_id for c in get_caches()):
            TestRun.fail("Cache should remain running after rejected disconnect command.")

    with TestRun.step("Stop cache"):
        cache.stop()
