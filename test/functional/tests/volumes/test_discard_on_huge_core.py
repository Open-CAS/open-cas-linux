#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from storage_devices.disk import DiskType, DiskTypeSet
from core.test_run import TestRun
from test_utils.size import Size, Unit

scsi_dev_size_gb = str(40 * 1024)


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug", virtual_gb=scsi_dev_size_gb, opts="1")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_discard_on_huge_core():
    """
        title: Test for handling discard request on huge CAS device.
        description: |
          Test if OpenCAS could handle discard requests on large CAS devices
          and if there is no RCU-sched stall in dmesg log.
        pass_criteria:
          - No system crash.
          - Discard request is handled without errors.
          - There is no RCU-sched type stall in dmesg log.
    """
    with TestRun.step("Clear dmesg log."):
        TestRun.executor.run_expect_success(f"dmesg -c")

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(10, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.scsi_debug_devices[0]

    with TestRun.step("Start cache and add SCSI device as core."):
        cache = casadm.start_cache(cache_part, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Execute blkdiscard on core few times."):
        # RCU-sched type stall sometimes appears in dmesg log after more
        # than one execution of blkdiscard.
        for _ in range(8):
            TestRun.executor.run_expect_success(f"blkdiscard {core.path}")

    with TestRun.step("Check dmesg for RCU-sched stall."):
        check_for_rcu_sched_type_stall()


def check_for_rcu_sched_type_stall():
    output = TestRun.executor.run_expect_success(f"dmesg")
    rcu_sched_found = False
    dmesg_log_id = ""

    results = output.stdout.splitlines()
    for line in results:
        if "rcu_sched" in line:
            rcu_sched_found = True
            dmesg_log_id = line[:line.index(".")]

        if rcu_sched_found and line.startswith(dmesg_log_id):
            TestRun.LOGGER.error(line)

    if not rcu_sched_found:
        TestRun.LOGGER.info("There is no rcu_sched type stall.")
