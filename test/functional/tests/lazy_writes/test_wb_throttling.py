#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import time
import random
from datetime import timedelta

from test_utils.size import Size, Unit
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_tools.iostat import IOstatExtended
from test_utils.os_utils import (
    kill_all_io,
    set_wbt_lat,
    get_wbt_lat,
    get_dut_cpu_number,
    wait,
)
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheModeTrait,
    CleaningPolicy,
    FlushParametersAcp,
    SeqCutOffPolicy,
    CacheLineSize,
    Time,
)
from test_tools.blktrace import BlkTrace, BlkTraceMask, ActionKind, RwbsKind


runtime = timedelta(days=30)


@pytest.mark.skip(
    reason="Since test lasts long time it shouldn't be executed during regular scope"
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_wb_throttling():
    """
        title: Test CAS with write back throttling enabled on exported object
        description: |
          Fill cache with data, run intensive IO (rwmix=74) with occasional trims.
        pass_criteria:
          - Hang task did not occurred
          - System did not crashed
    """
    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        set_wbt_lat(cache_device, 0)
        set_wbt_lat(core_device, 0)
        if core_device.size < cache_device.size:
            TestRun.LOGGER.info("Starting cache on partition")
            cache_device.create_partitions([core_device.size])
            cache_device = cache_device.partitions[0]

    with TestRun.step(
        f"Start cache with one core in write back with 64k cache line, NOP and disabled seq cutoff"
    ):
        cache = casadm.start_cache(cache_device, CacheMode.WB, CacheLineSize.LINE_64KiB)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        core = cache.add_core(core_device)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Check wbt_lat value on exported object"):
        wbt_lat_val = get_wbt_lat(core)
        TestRun.LOGGER.info(f"wbt_lat for exported object is {wbt_lat_val}")
        if wbt_lat_val == 0:
            TestRun.LOGGER.info(f"Setting wbt_lat for exported object to 75000us")
            set_wbt_lat(core, 75000)

    with TestRun.step("Fill cache with dirty data"):
        fio = get_fio_rw_cmd(core, write_percentage=100)
        fio_pid = fio.run_in_background()

        wait(
            lambda: core.get_statistics(percentage_val=True).usage_stats.dirty == 100,
            timeout=timedelta(hours=1),
            interval=timedelta(seconds=1),
        )
        kill_all_io()

    with TestRun.step("Run fio with rwmix=74% and occasional trims"):
        get_fio_rw_cmd(core, write_percentage=74).run_in_background()
        get_fio_trim(core).run_in_background()

    with TestRun.step("Change cleaning policy to ACP"):
        cache.set_cleaning_policy(CleaningPolicy.acp)

    with TestRun.step("Wait for IO processes to finish and print debug informations"):
        sleep_interval = timedelta(seconds=5)
        eta = runtime
        while eta.total_seconds() > 0:
            # Instead of explicit sleeping with `time.sleep()` iostat is used for waiting
            iostat = IOstatExtended.get_iostat_list(
                [core, cache_device, core_device],
                since_boot=False,
                interval=int(sleep_interval.total_seconds()),
            )
            TestRun.LOGGER.debug(f"{iostat}")
            eta -= sleep_interval
            TestRun.LOGGER.debug(f"ETA: {str(eta)}")

    with TestRun.step("Stop all caches"):
        kill_all_io()
        casadm.stop_all_caches()


def get_fio_rw_cmd(core, write_percentage):
    fio = (
        Fio()
        .create_command()
        .target(core)
        .read_write(ReadWrite.randrw)
        .write_percentage(write_percentage)
        .io_engine(IoEngine.libaio)
        .block_size(Size(16, Unit.Blocks4096))
        .run_time(runtime)
        .time_based(runtime)
        .io_depth(32)
        .num_jobs(72)
        .direct(1)
    )
    return fio


def get_fio_trim(core):
    fio = (
        Fio()
        .create_command()
        .target(core)
        .read_write(ReadWrite.trim)
        .io_engine(IoEngine.libaio)
        .block_size(Size(16, Unit.Blocks4096))
        .run_time(runtime)
        .time_based(runtime)
        .io_depth(1)
        .num_jobs(1)
        .direct(1)
    )
    return fio
