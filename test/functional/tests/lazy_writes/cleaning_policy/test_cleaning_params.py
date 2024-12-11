#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    FlushParametersAcp,
    SeqCutOffPolicy,
    FlushParametersAlru
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.udev import Udev
from types.size import Size, Unit
from types.time import Time


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policy_config():
    """
        title: Test for setting cleaning policy parameters.
        description: |
          Verify that cleaning policy parameters are set correctly
          and perform simple cleaning verification.
        pass_criteria:
          - Parameters displayed in CLI are reflecting the values set.
          - No data is flushed when using NOP policy.
          - Flushing occurs in expected time range for policies that flush data.
          - Set amount of data is flushed in a single iteration.
    """
    time_idle = Time(seconds=30)
    time_wake_up = Time(seconds=10)
    time_buffer = Time(seconds=2)
    data_to_flush = Size(50, Unit.Blocks4096)
    data_to_flush.set_unit(Unit.Byte)

    wait_before_flush = time_idle - time_buffer  # no flushes before that
    wait_after_flush = time_idle + time_wake_up  # flushes certain

    with TestRun.step("Prepare partitions."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(100, Unit.MiB)])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(200, Unit.MiB)])
        Udev.disable()

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev.partitions[0], force=True, cache_mode=CacheMode.WB)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Change cleaning policy to NOP."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        if cache.get_cleaning_policy() != CleaningPolicy.nop:
            TestRun.fail("NOP cleaning policy is not set!")

    with TestRun.step("Fill core with dirty data."):
        dd = (
            Dd().input("/dev/zero")
                .output(core.path)
                .block_size(Size(1, Unit.MiB))
                .oflag("direct")
        )
        dd.run()

    with TestRun.step(f"Check core statistics before and after waiting for "
                      f"{int(wait_after_flush.total_seconds())} seconds."):
        core_dirty_before = core.get_dirty_blocks()
        # Wait for longer than the time after which flushes would occur for other policies
        time.sleep(int(wait_after_flush.total_seconds()))
        core_dirty_after = core.get_dirty_blocks()
        if core_dirty_before != core_dirty_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics differ despite NOP policy used.\n"
                f"Dirty data before pause: {core_dirty_before}\n"
                f"Dirty data after pause: {core_dirty_after}"
            )

    with TestRun.step("Flush all dirty data."):
        cache.flush_cache()

    with TestRun.step("Change cleaning policy to ALRU and set parameters."):
        cache.set_cleaning_policy(CleaningPolicy.alru)

        params = FlushParametersAlru(
            wake_up_time=time_wake_up,
            staleness_time=time_idle,
            flush_max_buffers=int(data_to_flush.get_value(Unit.Blocks4096)),
            activity_threshold=time_idle
        )
        TestRun.LOGGER.info(str(params))
        cache.set_params_alru(params)

    with TestRun.step("Check if ALRU parameters are configured successfully."):
        new_params = cache.get_flush_parameters_alru()
        if cache.get_cleaning_policy() != CleaningPolicy.alru:
            TestRun.fail("ALRU cleaning policy is not set!")
        if new_params != params:
            TestRun.fail("ALRU parameters are not changed.\n"
                         f"Expected: {params}\nActual: {new_params}")

    with TestRun.step("Fill core with dirty data."):
        dd = (
            Dd().input("/dev/zero")
                .output(core.path)
                .block_size(Size(1, Unit.MiB))
                .oflag("direct")
        )
        dd.run()

    with TestRun.step(f"Check core statistics before and after waiting for "
                      f"{int(wait_before_flush.total_seconds())} seconds."):
        core_dirty_before = core.get_dirty_blocks()
        # Wait until shortly before expected flushes
        time.sleep(int(wait_before_flush.total_seconds()))
        core_dirty_after = core.get_dirty_blocks()
        if core_dirty_before != core_dirty_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics differ before assumed cleaning thread launch.\n"
                f"Dirty data before pause: {core_dirty_before}\n"
                f"Dirty data after pause: {core_dirty_after}"
            )

    with TestRun.step(f"Wait {int((wait_after_flush - wait_before_flush).total_seconds())} seconds "
                      f"and check statistics again."):
        # Wait until flushes are certain to occur
        time.sleep(int((wait_after_flush - wait_before_flush).total_seconds()))
        core_dirty_after = core.get_dirty_blocks()
        if core_dirty_before == core_dirty_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics are the same despite the ALRU policy was used.\n"
                f"Dirty data before pause: {core_dirty_before}\n"
                f"Dirty data after pause: {core_dirty_after}"
            )
        # Only check whether a minimum amount of data is flushed, as ALRU does not have
        # a configurable sleep time between active flushing iterations which would allow
        # to precisely estimate expected amount of data.
        elif core_dirty_before < core_dirty_after + data_to_flush:
            TestRun.LOGGER.error(
                f"Number of dirty blocks flushed differs from configured in policy.\n"
                f"Expected minimum dirty data flushed: {data_to_flush}\n"
                f"Actual dirty data flushed: "
                f"{core_dirty_before - core_dirty_after}"
            )

    with TestRun.step("Flush all dirty data."):
        cache.flush_cache()

    with TestRun.step("Change cleaning policy to ACP and set parameters."):
        cache.set_cleaning_policy(CleaningPolicy.acp)

        params = FlushParametersAcp(
            wake_up_time=time_wake_up,
            flush_max_buffers=int(data_to_flush.get_value(Unit.Blocks4096)),
        )
        TestRun.LOGGER.info(str(params))
        cache.set_params_acp(params)

    with TestRun.step("Check if ACP parameters are configured successfully."):
        new_params = cache.get_flush_parameters_acp()
        if cache.get_cleaning_policy() != CleaningPolicy.acp:
            TestRun.fail("ACP cleaning policy is not set!")
        if params != new_params:
            TestRun.fail("ACP parameters are not changed correctly.\n"
                         f"Expected: {params}\nActual: {new_params}")

    with TestRun.step("Fill core with dirty data."):
        dd = (
            Dd().input("/dev/zero")
                .output(core.path)
                .block_size(Size(1, Unit.MiB))
                .oflag("direct")
        )
        dd.run()

    with TestRun.step(f"Check core statistics before and after waiting for"
                      f" {int(time_wake_up.total_seconds())} seconds"):
        core_dirty_before = core.get_dirty_blocks()
        time.sleep(int(time_wake_up.total_seconds()))
        core_dirty_after = core.get_dirty_blocks()
        if core_dirty_before == core_dirty_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics are the same despite the ACP policy was used.\n"
                f"Dirty data before pause: {core_dirty_before}\n"
                f"Dirty data after pause: {core_dirty_after}"
            )
        elif core_dirty_before != core_dirty_after + data_to_flush:
            TestRun.LOGGER.error(
                f"Number of dirty blocks flushed differs from configured in policy.\n"
                f"Expected dirty data flushed: {data_to_flush}\n"
                f"Actual dirty data flushed: "
                f"{core_dirty_before - core_dirty_after}"
            )
