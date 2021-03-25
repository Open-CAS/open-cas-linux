#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
import time
import random
from datetime import timedelta

from test_utils.size import Size, Unit
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.fio.fio import Fio
from test_utils.os_utils import kill_all_io, Udev
from test_tools.fio.fio_param import ReadWrite, IoEngine
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheModeTrait,
    CleaningPolicy,
    FlushParametersAcp,
    CacheLineSize,
    SeqCutOffPolicy,
    FlushParametersAlru,
)
from test_tools.blktrace import BlkTrace, BlkTraceMask, ActionKind, RwbsKind
from test_utils.time import Time

time_to_wait_nop = Time(seconds=(30 * 0.9))
time_to_wait_alru_1st = Time(minutes=(1 * 0.9))
time_to_wait_alru_2nd = 1.5 * time_to_wait_alru_1st
time_to_wait_acp = Time(seconds=(10 * 0.9))
blocks_to_flush = 50


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


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policy_config():
    """

    """
    with TestRun.step("Prepare partitions."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(100, Unit.MiB)])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(200, Unit.MiB)])
        Udev.disable()

    with TestRun.step("Start cache with core."):
        cache = casadm.start_cache(cache_dev.partitions[0], force=True, cache_mode=CacheMode.WB)
        core = cache.add_core(core_dev.partitions[0])
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

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

    with TestRun.step("Check core statistics."):
        core_dirty_blocks_before = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))

    with TestRun.step(f"Wait {int((time_to_wait_nop * 1.2).total_seconds())} seconds and check "
                      f"statistics again."):
        time.sleep(int((time_to_wait_nop * 1.2).total_seconds()))
        core_dirty_blocks_after = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))
        if core_dirty_blocks_before != core_dirty_blocks_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics differs despite the NOP policy was used.\n"
                f"dirty data blocks before pause: {core_dirty_blocks_before}\n"
                f"dirty data blocks after pause: {core_dirty_blocks_after}"
            )

    with TestRun.step("Flush all dirty data."):
        cache.flush_cache()

    with TestRun.step("Change cleaning policy to ALRU and set parameters."):
        cache.set_cleaning_policy(CleaningPolicy.alru)
        default_params = cache.get_flush_parameters_alru()

        params = FlushParametersAlru(
            wake_up_time=time_to_wait_alru_1st,
            staleness_time=time_to_wait_alru_1st,
            flush_max_buffers=blocks_to_flush,
            activity_threshold=time_to_wait_alru_1st
        )
        cache.set_params_alru(params)
        new_params = cache.get_flush_parameters_alru()

    with TestRun.step("Check if ALRU parameters are configured successfully."):
        if cache.get_cleaning_policy() != CleaningPolicy.alru:
            TestRun.fail("ALRU cleaning policy is not set!")
        if default_params == new_params:
            TestRun.fail("ALRU parameters are not changed.")

    with TestRun.step("Fill core with dirty data."):
        dd = (
            Dd().input("/dev/zero")
                .output(core.path)
                .block_size(Size(1, Unit.MiB))
                .oflag("direct")
        )
        dd.run()

    with TestRun.step("Check core statistics."):
        core_dirty_blocks_before = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))

    with TestRun.step(f"Wait {int((time_to_wait_alru_1st * 1.2).total_seconds())} seconds "
                      f"and check statistics again."):
        time.sleep(int((time_to_wait_alru_1st * 1.2).total_seconds()))
        core_dirty_blocks_after = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))
        if core_dirty_blocks_before == core_dirty_blocks_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics are the same despite the ALRU policy was used.\n"
                f"dirty data blocks before pause: {core_dirty_blocks_before}\n"
                f"dirty data blocks after pause: {core_dirty_blocks_after}"
            )
        elif core_dirty_blocks_before != (core_dirty_blocks_after + blocks_to_flush):
            TestRun.LOGGER.error(
                f"Number of dirty blocks flushed differs from configured in policy.\n"
                f"configured dirty data blocks to flush: {blocks_to_flush}\n"
                f"currently dirty data blocks flushed: "
                f"{core_dirty_blocks_before - core_dirty_blocks_after}"
            )

    with TestRun.step(f"Wait {int((time_to_wait_alru_2nd * 1.2).total_seconds())} seconds "
                      f"and check statistics once again."):
        core_dirty_blocks_before = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))
        time.sleep(int((time_to_wait_alru_2nd * 1.2).total_seconds()))
        core_dirty_blocks_after = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))
        if core_dirty_blocks_before == core_dirty_blocks_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics are the same despite the ALRU policy was used.\n"
                f"dirty data blocks before pause: {core_dirty_blocks_before}\n"
                f"dirty data blocks after pause: {core_dirty_blocks_after}"
            )
        elif core_dirty_blocks_before != (core_dirty_blocks_after + blocks_to_flush):
            TestRun.LOGGER.error(
                f"Number of dirty blocks flushed differs from configured in policy.\n"
                f"configured dirty data blocks to flush: {blocks_to_flush}\n"
                f"currently dirty data blocks flushed: "
                f"{core_dirty_blocks_before - core_dirty_blocks_after}"
            )

    with TestRun.step("Flush all dirty data."):
        cache.flush_cache()

    with TestRun.step("Change cleaning policy to ACP and set parameters."):
        cache.set_cleaning_policy(CleaningPolicy.acp)
        default_params = cache.get_flush_parameters_acp()

        params = FlushParametersAcp(
            wake_up_time=time_to_wait_acp,
            flush_max_buffers=blocks_to_flush,
        )
        cache.set_params_acp(params)
        new_params = cache.get_flush_parameters_acp()

    with TestRun.step("Check if ACP parameters are configured successfully."):
        if cache.get_cleaning_policy() != CleaningPolicy.acp:
            TestRun.fail("ACP cleaning policy is not set!")
        if default_params == new_params:
            TestRun.fail("ACP parameters are not changed.")

    with TestRun.step("Fill core with dirty data."):
        dd = (
            Dd().input("/dev/zero")
                .output(core.path)
                .block_size(Size(1, Unit.MiB))
                .oflag("direct")
        )
        dd.run()

    with TestRun.step("Check core statistics."):
        core_dirty_blocks_before = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))

    with TestRun.step(f"Wait {int(time_to_wait_acp.total_seconds())} seconds and check "
                      f"statistics again."):
        time.sleep(int(time_to_wait_acp.total_seconds()))
        core_dirty_blocks_after = int(core.get_dirty_blocks().get_value(Unit.Blocks4096))
        if core_dirty_blocks_before == core_dirty_blocks_after:
            TestRun.LOGGER.error(
                f"Dirty data statistics are the same despite the ACP policy was used.\n"
                f"dirty data blocks before pause: {core_dirty_blocks_before}\n"
                f"dirty data blocks after pause: {core_dirty_blocks_after}"
            )
        elif core_dirty_blocks_before != (core_dirty_blocks_after + blocks_to_flush):
            TestRun.LOGGER.error(
                f"Number of dirty blocks flushed differs from configured in policy.\n"
                f"configured dirty data blocks to flush: {blocks_to_flush}\n"
                f"currently dirty data blocks flushed: "
                f"{core_dirty_blocks_before - core_dirty_blocks_after}"
            )


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
