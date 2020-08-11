#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
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
from test_utils.os_utils import kill_all_io
from test_tools.fio.fio_param import ReadWrite, IoEngine
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheModeTrait,
    CleaningPolicy,
    FlushParametersAcp,
    CacheLineSize,
    Time,
)
from test_tools.blktrace import BlkTrace, BlkTraceMask, ActionKind, RwbsKind


@pytest.mark.parametrizex(
    "cache_line_size",
    [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_16KiB, CacheLineSize.LINE_64KiB],
)
@pytest.mark.parametrizex(
    "cache_mode", CacheMode.with_any_trait(CacheModeTrait.LazyWrites)
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_acp_param_flush_max_buffers(cache_line_size, cache_mode):
    """
        title: Functional test for ACP flush-max-buffers parameter.
        description: |
          Verify if there is appropriate number of I/O requests between wake-up time intervals,
          which depends on flush-max-buffer parameter.
        pass_criteria:
          - ACP triggered dirty data flush
          - Number of writes to core is lower or equal than flush_max_buffers
    """
    with TestRun.step("Test prepare."):
        buffer_values = get_random_list(
            min_val=FlushParametersAcp.acp_params_range().flush_max_buffers[0],
            max_val=FlushParametersAcp.acp_params_range().flush_max_buffers[1],
            n=10,
        )

        default_config = FlushParametersAcp.default_acp_params()
        acp_configs = [
            FlushParametersAcp(flush_max_buffers=buf) for buf in buffer_values
        ]
        acp_configs.append(default_config)

    with TestRun.step("Prepare partitions."):
        core_size = Size(10, Unit.GibiByte)
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions([Size(5, Unit.GibiByte)])
        core_device.create_partitions([core_size])

    with TestRun.step(
        f"Start cache in {cache_mode} with {cache_line_size} and add core."
    ):
        cache = casadm.start_cache(
            cache_device.partitions[0], cache_mode, cache_line_size
        )
        core = cache.add_core(core_device.partitions[0])

    with TestRun.step("Set cleaning policy to NOP."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Start IO in background."):
        fio = get_fio_cmd(core, core_size)
        fio_pid = fio.run_in_background()
        time.sleep(10)

    with TestRun.step("Set cleaning policy to ACP."):
        cache.set_cleaning_policy(CleaningPolicy.acp)

    with TestRun.group("Verify IO number for different max_flush_buffers values."):
        for acp_config in acp_configs:
            with TestRun.step(f"Setting {acp_config}"):
                cache.set_params_acp(acp_config)
            with TestRun.step(
                "Using blktrace verify if there is appropriate number of I/O requests, "
                "which depends on flush-max-buffer parameter."
            ):
                blktrace = BlkTrace(core.core_device, BlkTraceMask.write)
                blktrace.start_monitoring()
                time.sleep(20)
                blktrace_output = blktrace.stop_monitoring()

                cleaning_started = False
                flush_writes = 0
                for (prev, curr) in zip(blktrace_output, blktrace_output[1:]):
                    if cleaning_started and write_to_core(prev, curr):
                        flush_writes += 1
                    if new_acp_iteration(prev, curr):
                        if cleaning_started:
                            if flush_writes <= acp_config.flush_max_buffers:
                                flush_writes = 0
                            else:
                                TestRun.LOGGER.error(
                                    f"Incorrect number of handled io requests. "
                                    f"Expected {acp_configs.flush_max_buffers} - "
                                    f"actual {flush_writes}"
                                )
                                flush_writes = 0

                        cleaning_started = True

                if not cleaning_started:
                    TestRun.fail(f"ACP flush not triggered for {acp_config}")

    with TestRun.step("Stop all caches"):
        kill_all_io()
        casadm.stop_all_caches()


@pytest.mark.parametrizex(
    "cache_line_size",
    [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_16KiB, CacheLineSize.LINE_64KiB],
)
@pytest.mark.parametrizex(
    "cache_mode", CacheMode.with_any_trait(CacheModeTrait.LazyWrites)
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_acp_param_wake_up_time(cache_line_size, cache_mode):
    """
        title: Functional test for ACP wake-up parameter.
        description: |
          Verify if interval between ACP cleaning iterations is not longer than
          wake-up time parameter value.
        pass_criteria:
          - ACP flush iterations are triggered with defined frequency.
    """
    with TestRun.step("Test prepare."):
        error_threshold_ms = 50
        generated_vals = get_random_list(
            min_val=FlushParametersAcp.acp_params_range().wake_up_time[0],
            max_val=FlushParametersAcp.acp_params_range().wake_up_time[1],
            n=10,
        )
        acp_configs = []
        for config in generated_vals:
            acp_configs.append(
                FlushParametersAcp(wake_up_time=Time(milliseconds=config))
            )
        acp_configs.append(FlushParametersAcp.default_acp_params())

    with TestRun.step("Prepare partitions."):
        core_size = Size(10, Unit.GibiByte)
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions([Size(5, Unit.GibiByte)])
        core_device.create_partitions([core_size])

    with TestRun.step(
        f"Start cache in {cache_mode} with {cache_line_size} and add core."
    ):
        cache = casadm.start_cache(
            cache_device.partitions[0], cache_mode, cache_line_size
        )
        core = cache.add_core(core_device.partitions[0])

    with TestRun.step("Set cleaning policy to NOP."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Start IO in background."):
        fio = get_fio_cmd(core, core_size)
        fio_pid = fio.run_in_background()
        time.sleep(10)

    with TestRun.step("Set cleaning policy to ACP."):
        cache.set_cleaning_policy(CleaningPolicy.acp)

    with TestRun.group("Verify IO number for different wake_up_time values."):
        for acp_config in acp_configs:
            with TestRun.step(f"Setting {acp_config}"):
                cache.set_params_acp(acp_config)
                accepted_interval_threshold = (
                    acp_config.wake_up_time.total_milliseconds() + error_threshold_ms
                )
            with TestRun.step(
                "Using blktrace verify if interval between ACP cleaning iterations "
                f"is shorter or equal than wake-up parameter value "
                f"(including {error_threshold_ms}ms error threshold)"
            ):
                blktrace = BlkTrace(core.core_device, BlkTraceMask.write)
                blktrace.start_monitoring()
                time.sleep(15)
                blktrace_output = blktrace.stop_monitoring()

                for (prev, curr) in zip(blktrace_output, blktrace_output[1:]):
                    if not new_acp_iteration(prev, curr):
                        continue

                    interval_ms = (curr.timestamp - prev.timestamp) / 10 ** 6

                    if interval_ms > accepted_interval_threshold:
                        TestRun.LOGGER.error(
                            f"{interval_ms} is not within accepted range for "
                            f"{acp_config.wake_up_time.total_milliseconds()} "
                            f"wake_up_time param value."
                        )

    with TestRun.step("Stop all caches"):
        kill_all_io()
        casadm.stop_all_caches()


def get_random_list(min_val, max_val, n):
    # Split given range into n parts and get one random number from each
    step = int((max_val - min_val + 1) / n)
    generated_vals = [
        random.randint(i, i + step) for i in range(min_val, max_val, step)
    ]
    return generated_vals


def new_acp_iteration(prev, curr):
    return (
        prev.action == ActionKind.IoCompletion
        and curr.action == ActionKind.IoDeviceRemap
    )


def write_to_core(prev, curr):
    return prev.action == ActionKind.IoHandled and curr.rwbs & RwbsKind.W


def get_fio_cmd(core, core_size):
    fio = (
        Fio()
        .create_command()
        .target(core)
        .read_write(ReadWrite.write)
        .io_engine(IoEngine.libaio)
        .io_size(Size(10, Unit.TebiByte))
        .size(core_size)
        .block_size(Size(1, Unit.Blocks4096))
        .run_time(timedelta(seconds=9999))
        .io_depth(32)
        .num_jobs(1)
        .direct(1)
    )
    return fio
