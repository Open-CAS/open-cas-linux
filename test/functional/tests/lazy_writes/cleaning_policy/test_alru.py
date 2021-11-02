#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, FlushParametersAlru, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.os_utils import Udev, kill_all_io
from test_utils.size import Size, Unit
from test_utils.time import Time


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
