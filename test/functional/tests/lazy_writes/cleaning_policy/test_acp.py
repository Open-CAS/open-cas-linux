#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import time
from collections import namedtuple
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheModeTrait,
    CleaningPolicy,
    FlushParametersAcp,
    CacheLineSize
)
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType
from test_tools.blktrace import BlkTrace, BlkTraceMask, ActionKind, RwbsKind
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import kill_all_io
from test_utils.size import Size, Unit
from test_utils.time import Time


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
def test_acp_functional(cache_mode):
    """
        title: Validate ACP behavior.
        description: |
          Validate that ACP is cleaning dirty data from chunks bucket - sorted by number of
          dirty pages.
        pass_criteria:
          - All chunks are cleaned in proper order
    """
    chunks_count = 8
    chunk_size = Size(100, Unit.MebiByte)
    chunk_list = []

    def sector_in_chunk(chunk, blktrace_header):
        sector_to_size = Size(blktrace_header.sector_number, Unit.Blocks512)
        return chunk.offset <= sector_to_size < chunk.offset + chunk_size

    def get_header_chunk(bucket_chunks, blktrace_header):
        return next((c for c in bucket_chunks if sector_in_chunk(c, blktrace_header)), None)

    def sector_in_tested_region(blktrace_header, list_of_chunks):
        return any([sector_in_chunk(c, blktrace_header) for c in list_of_chunks])

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']
        cache_device.create_partitions([chunk_size * chunks_count])
        cache_device = cache_device.partitions[0]

    with TestRun.step("Start cache in WB mode, set cleaning policy to NOP "
                      "and add whole disk as core."):
        cache = casadm.start_cache(cache_device, cache_mode)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        core = cache.add_core(core_device)

    with TestRun.step("Run separate random writes with random amount of data on every "
                      "100 MiB part of CAS device."):
        Chunk = namedtuple('Chunk', 'offset writes_size')
        random_chunk_writes = random.sample(range(1, 101), chunks_count)
        for i in range(chunks_count):
            c = Chunk(chunk_size * i, Size(random_chunk_writes[i], Unit.MebiByte))
            chunk_list.append(c)

        fio = (Fio()
               .create_command()
               .io_engine(IoEngine.sync)
               .read_write(ReadWrite.randwrite)
               .direct()
               .size(chunk_size)
               .block_size(Size(1, Unit.Blocks4096))
               .target(f"{core.path}"))
        for chunk in chunk_list:
            fio.add_job().offset(chunk.offset).io_size(chunk.writes_size)
        fio.run()

        dirty_blocks = cache.get_dirty_blocks()
        if dirty_blocks == Size.zero():
            TestRun.fail("No dirty data on cache after IO.")
        TestRun.LOGGER.info(str(cache.get_statistics()))

    with TestRun.step("Switch cleaning policy to ACP and start blktrace monitoring."):
        trace = BlkTrace(core.core_device, BlkTraceMask.write)
        trace.start_monitoring()

        initial_dirty_blocks = cache.get_dirty_blocks()
        cache.set_cleaning_policy(CleaningPolicy.acp)
        while cache.get_dirty_blocks() > Size.zero():
            time.sleep(10)
            if cache.get_dirty_blocks() == initial_dirty_blocks:
                TestRun.fail(f"No data flushed in 10s.\n{str(cache.get_statistics())}")
            initial_dirty_blocks = cache.get_dirty_blocks()

        TestRun.LOGGER.info(str(cache.get_statistics()))

        action_kind = ActionKind.IoHandled
        output = trace.stop_monitoring()
        blktrace_output = [h for h in output if h.action == action_kind
                           and RwbsKind.F not in h.rwbs]

        if not blktrace_output:
            TestRun.fail(f"No {action_kind.name} entries in blktrace output!")
        TestRun.LOGGER.debug(f"Blktrace headers count: {len(blktrace_output)}.")

    with TestRun.step("Using blktrace verify that cleaning thread cleans data from "
                      "all CAS device parts in proper order."):
        all_writes_ok = True
        last_sector = None
        max_percent = 100
        bucket_chunks = []
        current_chunk = None

        for header in blktrace_output:
            # Sector not in current chunk - search for the next chunk
            if current_chunk is None or \
                    not sector_in_chunk(current_chunk, header):
                # Search for bucket with chunks that contain most dirty data
                while not bucket_chunks and max_percent > 0:
                    bucket_chunks = [chunk for chunk in chunk_list
                                     if max_percent >= chunk.writes_size.get_value(Unit.MebiByte)
                                     > max_percent - 10]
                    max_percent -= 10

                if not bucket_chunks:
                    TestRun.fail(f"No chunks left for sector {header.sector_number} "
                                 f"({Size(header.sector_number, Unit.Blocks512)}).")

                # Get chunk within current bucket where current header sector is expected
                chunk = get_header_chunk(bucket_chunks, header)
                if not chunk:
                    TestRun.LOGGER.error(f"Sector {header.sector_number} "
                                         f"({Size(header.sector_number, Unit.Blocks512)}) "
                                         f"not in current bucket.")
                    all_writes_ok = False
                    if not sector_in_tested_region(header, chunk_list):
                        TestRun.LOGGER.error(f"Sector {header.sector_number} "
                                             f"({Size(header.sector_number, Unit.Blocks512)}) "
                                             f"outside of any tested chunk.")
                    continue

                # Set new chunk as current
                if current_chunk:
                    TestRun.LOGGER.info(f"Writes to chunk: {write_counter}")
                current_chunk = chunk
                write_counter = 1
                bucket_chunks.remove(chunk)
                last_sector = header.sector_number
                TestRun.LOGGER.debug(f"First written sector in new chunk: {header.sector_number} "
                                     f"({Size(header.sector_number, Unit.Blocks512)})")
                continue

            # Sector in current chunk - check sequential order
            if last_sector is None or header.sector_number >= last_sector:
                last_sector = header.sector_number
            else:
                TestRun.LOGGER.error(f"Sectors in chunk <{current_chunk.offset}, "
                                     f"{str(current_chunk.offset + chunk_size)}) written in bad "
                                     f"order - sector {header.sector_number} ("
                                     f"{Size(header.sector_number, Unit.Blocks512)}) after sector "
                                     f"{last_sector} ({Size(last_sector, Unit.Blocks512)})")
                all_writes_ok = False
            write_counter += 1
        TestRun.LOGGER.info(f"Writes to chunk: {write_counter}")

        if all_writes_ok:
            TestRun.LOGGER.info("All sectors written in proper order.")


@pytest.mark.parametrizex(
    "cache_line_size",
    [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_16KiB, CacheLineSize.LINE_64KiB],
)
@pytest.mark.parametrizex(
    "cache_mode", CacheMode.with_any_trait(CacheModeTrait.LazyWrites)
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k]))
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
            FlushParametersAcp(flush_max_buffers=buf, wake_up_time=Time(seconds=1)) for buf in
            buffer_values
        ]
        acp_configs.append(default_config)

    with TestRun.step("Prepare partitions."):
        core_size = Size(5, Unit.GibiByte)
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions([Size(10, Unit.GibiByte)])
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
        fio.run_in_background()
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
                    if cleaning_started and write_to_core(prev):
                        flush_writes += 1
                    if new_acp_iteration(prev, curr):
                        if cleaning_started:
                            if flush_writes <= acp_config.flush_max_buffers:
                                flush_writes = 0
                            else:
                                TestRun.LOGGER.error(
                                    f"Incorrect number of handled io requests. "
                                    f"Expected {acp_config.flush_max_buffers} - "
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
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k]))
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
        core_size = Size(5, Unit.GibiByte)
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions([Size(10, Unit.GibiByte)])
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
        fio.run_in_background()
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


def write_to_core(prev):
    return prev.action == ActionKind.IoHandled and prev.rwbs & RwbsKind.W and prev.byte_count > 0


def get_fio_cmd(core, core_size):
    fio = (
        Fio()
        .create_command()
        .target(core)
        .read_write(ReadWrite.write)
        .io_engine(IoEngine.libaio)
        .size(core_size)
        .block_size(Size(1, Unit.Blocks4096))
        .run_time(timedelta(hours=99))
        .time_based()
        .io_depth(32)
        .num_jobs(1)
        .direct(1)
    )
    return fio
