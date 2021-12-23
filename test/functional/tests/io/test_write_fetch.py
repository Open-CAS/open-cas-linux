#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import uuid
from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, CacheModeTrait
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", [mode for mode in CacheMode if
                                        CacheModeTrait.InsertWrite & mode.get_traits(mode)])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_write_fetch_full_misses(cache_mode, cache_line_size):
    """
        title: No caching of full write miss operations with block size smaller than cache line size
        description: |
          Validate CAS ability to not cache entire cache line size for full write miss operations
          when block size is smaller than cache line size – no fetch for writes
        pass_criteria:
          - Appropriate number of write full misses and writes to cache in cache statistics
          - Appropriate number of writes to cache in iostat
    """
    io_size = Size(300, Unit.MebiByte)

    with TestRun.step("Start cache and add core."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache = casadm.start_cache(cache_disk, cache_mode, cache_line_size)
        Udev.disable()
        core = cache.add_core(core_disk)
    with TestRun.step("Run writes to CAS device using fio."):
        io_stats_before_io = cache_disk.get_io_stats()
        blocksize = cache_line_size.value / 2
        skip_size = cache_line_size.value / 2
        run_fio(target=core.path,
                operation_type=ReadWrite.write,
                skip=skip_size,
                blocksize=blocksize,
                io_size=io_size)
    with TestRun.step("Verify CAS statistics for write full misses and writes to cache."):
        check_statistics(cache=cache, blocksize=blocksize, skip_size=skip_size, io_size=io_size)
    with TestRun.step("Verify number of writes to cache device using iostat. Shall be half of "
                      f"io size ({str(io_size / 2)}) + metadata for WB."):
        check_io_stats(cache_disk=cache_disk,
                       cache=cache,
                       io_stats_before=io_stats_before_io,
                       io_size=io_size,
                       blocksize=blocksize,
                       skip_size=skip_size)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", [mode for mode in CacheMode if
                                        CacheModeTrait.InsertWrite & CacheMode.get_traits(mode)])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_write_fetch_partial_misses(cache_mode, cache_line_size):
    """
        title: No caching of partial write miss operations
        description: |
          Validate CAS ability to not cache entire cache line size for
          partial write miss operations
        pass_criteria:
          - Appropriate number of write partial misses, write hits and writes to cache
            in cache statistics
          - Appropriate number of writes to cache in iostat
    """
    pattern = f"0x{uuid.uuid4().hex}"
    io_size = Size(600, Unit.MebiByte)

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        core_disk.create_partitions([io_size + Size(1, Unit.MebiByte)])
        core_part = core_disk.partitions[0]

    with TestRun.step("Fill core partition with pattern."):
        cache_mode_traits = CacheMode.get_traits(cache_mode)
        if CacheModeTrait.InsertRead in cache_mode_traits:
            run_fio(target=core_part.path,
                    operation_type=ReadWrite.write,
                    blocksize=Size(4, Unit.KibiByte),
                    io_size=io_size,
                    verify=True,
                    pattern=pattern)
        else:
            TestRun.LOGGER.info(f"Skipped for {cache_mode} cache mode.")

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_disk, cache_mode, cache_line_size)
        Udev.disable()
        core = cache.add_core(core_part)
    with TestRun.step("Cache half of file."):
        operation_type = ReadWrite.read if CacheModeTrait.InsertRead in cache_mode_traits \
            else ReadWrite.write
        run_fio(target=core.path,
                operation_type=operation_type,
                skip=cache_line_size.value,
                blocksize=cache_line_size.value,
                io_size=io_size,
                verify=True,
                pattern=pattern)
        if CacheModeTrait.InsertRead not in cache_mode_traits:
            cache.flush_cache()
        casadm.reset_counters(cache.cache_id, core.core_id)
    with TestRun.step("Run writes to CAS device using fio."):
        io_stats_before_io = cache_disk.get_io_stats()
        blocksize = cache_line_size.value / 2 * 3
        skip_size = cache_line_size.value / 2
        run_fio(target=core.path,
                operation_type=ReadWrite.write,
                skip=skip_size,
                blocksize=blocksize,
                io_size=io_size)
    with TestRun.step("Verify CAS statistics for partial misses, write hits and writes to cache."):
        check_statistics(cache=cache,
                         blocksize=blocksize,
                         skip_size=skip_size,
                         io_size=io_size,
                         partial_misses=True)
    with TestRun.step("Verify number of writes to cache device using iostat. Shall be 0.75 of "
                      f"io size ({str(io_size * 0.75)}) + metadata for cache mode with write "
                      f"insert feature."):
        check_io_stats(cache_disk=cache_disk,
                       cache=cache,
                       io_stats_before=io_stats_before_io,
                       io_size=io_size,
                       blocksize=blocksize,
                       skip_size=skip_size)


# Methods used in tests:
def check_io_stats(cache_disk, cache, io_stats_before, io_size, blocksize, skip_size):
    io_stats_after = cache_disk.get_io_stats()
    logical_block_size = int(TestRun.executor.run(
        f"cat /sys/block/{cache_disk.device_name}/queue/logical_block_size").stdout)
    diff = io_stats_after.sectors_written - io_stats_before.sectors_written
    written_sector_size = Size(logical_block_size) * diff
    TestRun.LOGGER.info(f"Sectors written: "
                        f"{io_stats_after.sectors_written - io_stats_before.sectors_written} "
                        f"({written_sector_size.get_value(Unit.MebiByte)}MiB)")

    expected_writes = io_size * (blocksize / (blocksize + skip_size))

    cache_mode_traits = CacheMode.get_traits(cache.get_cache_mode())
    if CacheModeTrait.InsertWrite | CacheModeTrait.LazyWrites in cache_mode_traits:
        # Metadata size is 4KiB per each cache line
        metadata_size = (io_size / cache.get_cache_line_size().value) * Size(4, Unit.KibiByte)
        expected_writes += metadata_size

    if not validate_value(expected_writes.get_value(), written_sector_size.get_value()):
        TestRun.LOGGER.error(f"IO stat writes to cache "
                             f"({written_sector_size.get_value(Unit.MebiByte)}MiB) "
                             f"inconsistent with expected value "
                             f"({expected_writes.get_value(Unit.MebiByte)}MiB)")


def validate_value(expected, actual):
    if expected == 0:
        return actual == 0
    val = abs(100 * actual / expected - 100)
    return val < 1


def check_statistics(cache, blocksize, skip_size, io_size, partial_misses=False):
    cache_stats = cache.get_statistics()
    TestRun.LOGGER.info(str(cache_stats))
    if not partial_misses:
        requests = cache_stats.request_stats.write.full_misses
    else:
        requests = cache_stats.request_stats.write.part_misses
    expected_requests = io_size / (blocksize + skip_size)
    if not validate_value(expected_requests, requests):
        TestRun.LOGGER.error(f"{'Partial misses' if partial_misses else 'Write full misses'} "
                             f"({requests} requests) inconsistent with "
                             f"expected value ({expected_requests} requests)")

    write_hits = cache_stats.request_stats.write.hits
    if not validate_value(expected_requests,
                          expected_requests - write_hits):
        TestRun.LOGGER.error(f"Write hits ({write_hits} requests) inconsistent with "
                             f"expected value (0 requests)")

    expected_writes = io_size * (blocksize / (blocksize + skip_size))
    writes_to_cache = cache_stats.block_stats.cache.writes
    if not validate_value(expected_writes.get_value(), writes_to_cache.get_value()):
        TestRun.LOGGER.error(f"Writes to cache ({writes_to_cache} MiB) inconsistent with "
                             f"expected value ({expected_writes} MiB)")


def run_fio(target, operation_type: ReadWrite, blocksize, io_size, verify=False, pattern=None,
            skip: Size = None):
    fio_operation_type = operation_type.name
    if skip:
        fio_operation_type += f":{int(skip.get_value(Unit.KibiByte))}k"
    fio = (Fio()
           .create_command()
           .target(target)
           .io_engine(IoEngine.sync)
           .block_size(blocksize)
           .direct()
           .file_size(io_size)
           .set_param("readwrite", fio_operation_type))
    if verify:
        fio.verification_with_pattern(pattern)
    fio.run()
