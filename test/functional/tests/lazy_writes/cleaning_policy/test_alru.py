#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import time
import pytest

from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    FlushParametersAlru,
    SeqCutOffPolicy,
    CacheLineSize,
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_tools.os_tools import kill_all_io
from test_tools.udev import Udev
from type_def.size import Size, Unit
from type_def.time import Time


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_alru_no_idle():
    """
    title: Test ALRU with activity threshold set to 0
    description: |
      Verify that ALRU is able to perform cleaning if cache is under constant load and
      activity threshold is set to 0. Constant load is performed by using fio instance running
      in background.
    pass_criteria:
      - Dirty cache lines are cleaned successfully.
    """

    with TestRun.step("Prepare configuration"):
        cache, core = prepare()

    with TestRun.step("Prepare dirty data to be cleaned"):
        bg_size = Size(2, Unit.MiB)
        (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .offset(bg_size)
            .size(Size(10, Unit.MiB))
            .block_size(Size(4, Unit.KiB))
            .target(core)
            .direct()
            .read_write(ReadWrite.randwrite)
            .run()
        )

    with TestRun.step("Run background fio"):
        (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(bg_size)
            .block_size(Size(4, Unit.KiB))
            .target(core)
            .direct()
            .time_based(True)
            .run_time(timedelta(hours=1))
            .read_write(ReadWrite.randwrite)
            .run_in_background()
        )

    with TestRun.step("Verify that cache is dirty"):
        # Wait for bg fio to dirty whole workset
        time.sleep(5)
        dirty_before = cache.get_statistics().usage_stats.dirty

        if dirty_before == Size(0):
            TestRun.fail("Cache should be dirty")

    with TestRun.step("Check that cleaning doesn't occur under constant load"):
        time.sleep(5)

        dirty_now = cache.get_statistics().usage_stats.dirty

        if dirty_before > dirty_now:
            TestRun.fail(
                f"Cleaning has run, while it shouldn't"
                f" (dirty down from {dirty_before} to {dirty_now}"
            )

    with TestRun.step("Set 0 idle time and wake up time for ALRU"):
        cache.set_params_alru(FlushParametersAlru(activity_threshold=Time(0), wake_up_time=Time(0)))

    with TestRun.step("Check that cleaning is progressing"):
        time.sleep(5)

        if dirty_before <= cache.get_statistics().usage_stats.dirty:
            TestRun.fail("Cleaning didn't run")

    kill_all_io()


def prepare():
    cache_dev = TestRun.disks["cache"]
    core_dev = TestRun.disks["core"]

    cache_dev.create_partitions([Size(100, Unit.MiB)])
    core_dev.create_partitions([Size(200, Unit.MiB)])

    Udev.disable()
    cache = casadm.start_cache(cache_dev.partitions[0], force=True, cache_mode=CacheMode.WB)
    core = cache.add_core(core_dev.partitions[0])
    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
    cache.set_cleaning_policy(CleaningPolicy.alru)
    cache.set_params_alru(
        FlushParametersAlru(
            activity_threshold=Time(seconds=100),
            staleness_time=Time(seconds=1),
        )
    )

    return cache, core


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("inertia", [Size.zero(), Size(1500, Unit.MiB)])
@pytest.mark.parametrizex(
    "cache_line_size",
    [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB],
)
def test_alru_dirty_ratio_inertia_no_cleaning_if_dirty_below_threshold(
    cache_line_size: CacheLineSize, inertia: Unit
):
    """
    title: Test ALRU dirty ratio inertia — no cleaning below threshold
    description: |
      Verify that ALRU cleaning is not triggered when the number of dirty cache lines is lower than
      (threshold - intertia)
    pass_criteria:
      - The cleaning is not triggered when dirty data doesn't exceed the specified threshold.
    """
    with TestRun.step("Prepare disks for cache and core"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(3, Unit.GiB)])
        core_dev.create_partitions([Size(10, Unit.GiB)])

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(
            cache_dev.partitions[0],
            cache_line_size=cache_line_size,
            force=True,
            cache_mode=CacheMode.WB,
        )
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Set ALRU and disable sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.alru)

    with TestRun.step(f"Set alru params"):
        cache.set_params_alru(
            FlushParametersAlru(
                staleness_time=Time(seconds=3600),
                wake_up_time=Time(seconds=1),
                activity_threshold=Time(milliseconds=1000),
                dirty_ratio_threshold=90,
                dirty_ratio_inertia=inertia,
            )
        )

    with TestRun.step("Run write workload to reach ~2GiB (≈66% of 3GiB) dirty data"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(cache.size * 0.66)
            .block_size(Size(4, Unit.KiB))
            .target(core)
            .direct()
            .read_write(ReadWrite.randwrite)
        )
        fio.run()

    with TestRun.step("Capture baseline dirty usage after I/O settles"):
        time.sleep(2)
        dirty_before_pct = cache.get_statistics(percentage_val=True).usage_stats.dirty
        dirty_before = cache.get_statistics().usage_stats.dirty
        if dirty_before_pct <= 60:
            TestRun.fail(
                f"Exception: Precondition not met: dirty cache lines must exceed 60% after "
                f"I/O settles (dirty={dirty_before}, dirty%={dirty_before_pct}%). Aborting test."
            )

    with TestRun.step("Idle and verify dirty cache lines do not change and remain below threshold"):
        time.sleep(30)
        dirty_after = cache.get_statistics().usage_stats.dirty

        if dirty_before > dirty_after:
            TestRun.fail(
                f"No flushing shall occur when dirty < threshold (dirty before={dirty_before}, "
                f"dirty after={dirty_after}, threshold={dirty_ratio_threshold}%)"
            )
