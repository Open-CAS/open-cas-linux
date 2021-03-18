#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
from time import sleep

from test_tools.dd import Dd
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, ErrorFilter
from test_tools.device_mapper import ErrorDevice, DmTable
from core.test_run import TestRun
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    SeqCutOffPolicy,
    CleaningPolicy, CacheModeTrait,
)
from storage_devices.disk import DiskTypeSet, DiskType
from test_utils.io_stats import IoStats
from test_utils.size import Size, Unit

cache_part_size = Size(400, Unit.MiB)


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cache_mode", [CacheMode.WT, CacheMode.WA])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd4k, DiskType.hdd]))
def test_error_device_as_cache_clean(cache_mode, cache_line_size):
    """
        title: Validate Open CAS ability to handle read hit I/O error on cache device for clean data
        description: |
          Perform I/O on exported object while error device is cache device and validate if
          errors are present in Open CAS stats.
        pass_criteria:
          - Write error count in fio is zero
          - Read error count in fio is zero
          - Write error count in cache statistics is zero
          - Total error count in cache statistics is greater than zero
    """
    with TestRun.step("Prepare error device and setup cache and core."):
        cache, cores, error_dev, cache_dev = prepare_configuration(cache_mode, cache_line_size, 1)

    if cache_mode == CacheMode.WA:
        with TestRun.step("Read core to null block."):
            Dd().input(cores[0]) \
                .output('/dev/null') \
                .iflag('direct') \
                .block_size(cache_line_size.value) \
                .run()

    with TestRun.step("Run fio against core to fill it with pattern."):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part_size)
            .read_write(ReadWrite.randwrite)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part_size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no write errors."):
        if fio_errors != 0:
            TestRun.fail("Fio reported write errors!")

    with TestRun.step("Stop cache and enable errors on cache device (after metadata area)."):
        cache_size = cache.size
        metadata_size = cache.get_metadata_size() + Size(1, Unit.MiB)
        cache.stop()

        error_dev.change_table(
            error_table(cache_size, metadata_size).fill_gaps(cache_dev)
        )

    with TestRun.step("Load cache and reset counters."):
        cache = casadm.load_cache(error_dev)
        cache.reset_counters()

    with TestRun.step("Run fio against core with pattern verification."):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part_size)
            .read_write(ReadWrite.randread)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part_size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no read errors."):
        if fio_errors != 0:
            TestRun.fail("Fio reported read errors!")

    with TestRun.step("Check cache error statistics."):
        stats = cache.get_statistics()
        write_errors_in_cache = stats.error_stats.cache.writes
        if write_errors_in_cache != 0:
            TestRun.fail(f"Write errors in cache stats detected ({write_errors_in_cache})!")

        total_errors_in_cache = stats.error_stats.cache.total
        if total_errors_in_cache == 0:
            TestRun.fail(
                f"Total errors in cache stats ({total_errors_in_cache}) should be greater than 0!"
            )

        TestRun.LOGGER.info(f"Total number of I/O errors in cache stats: {total_errors_in_cache}.")


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd4k, DiskType.hdd]))
def test_error_device_as_cache_dirty(cache_mode, cache_line_size):
    """
        title: Validate Open CAS ability to handle read hit I/O error on cache device for dirty data
        description: |
          Perform I/O on exported object while error device is used as cache device and validate if
          errors are present in Open CAS statistics and no I/O traffic is detected on cores after
          enabling errors on cache device.
        pass_criteria:
          - Write error count in fio is zero
          - Read error count in fio is greater than zero
          - I/O error count in cache statistics is greater than zero
          - I/O traffic stop on the second core after enabling errors on cache device is stopped
    """
    with TestRun.step("Prepare error device and setup cache and cores."):
        cache, cores, error_dev, cache_dev = prepare_configuration(cache_mode, cache_line_size, 2)

    with TestRun.step("Run fio against the first core to fill it with pattern."):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part_size)
            .read_write(ReadWrite.randwrite)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part_size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no write errors."):
        if fio_errors != 0:
            TestRun.fail("Fio reported write errors!")

    with TestRun.step("Stop cache and enable errors on cache device (after metadata area)."):
        cache_size = cache.size
        metadata_size = cache.get_metadata_size() + Size(1, Unit.MiB)
        cache.stop(True)

        error_dev.change_table(
            error_table(cache_size, metadata_size).fill_gaps(cache_dev)
        )

    with TestRun.step("Load cache and reset counters."):
        cache = casadm.load_cache(error_dev)
        cache.reset_counters()

    with TestRun.step("Run fio against the first core with pattern verification."):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part_size)
            .read_write(ReadWrite.randread)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part_size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported read errors."):
        if fio_errors == 0:
            TestRun.fail("Fio does not reported read errors!")
        TestRun.LOGGER.info(f"Number of fio read errors: {fio_errors}.")

    with TestRun.step("Check the second core I/O traffic."):
        core_2_errors_before = IoStats.get_io_stats(cores[1].get_device_id())
        sleep(5)
        core_2_errors_after = IoStats.get_io_stats(cores[1].get_device_id())

        if (core_2_errors_after.reads > core_2_errors_before.reads
                or core_2_errors_after.writes > core_2_errors_before.writes):
            TestRun.fail(f"I/O traffic detected on the second core ({cores[1]})!")
        else:
            TestRun.LOGGER.info(f"I/O traffic stopped on the second core ({cores[1]}).")

    with TestRun.step("Check total cache error statistics."):
        stats = cache.get_statistics()
        total_errors_in_cache = stats.error_stats.cache.total
        if total_errors_in_cache == 0:
            TestRun.fail(
                f"Total errors in cache stats ({total_errors_in_cache}) should be greater than 0!"
            )
        TestRun.LOGGER.info(f"Total number of I/O errors in cache stats: {total_errors_in_cache}.")


def error_table(size: Size, offset: Size):
    return DmTable.uniform_error_table(
        start_lba=int(offset.get_value(Unit.Blocks512)),
        stop_lba=int(size.get_value(Unit.Blocks512)),
        num_error_zones=100,
        error_zone_size=Size(5, Unit.Blocks512),
    )


def prepare_configuration(cache_mode, cache_line_size, cores_number):
    cache_device = TestRun.disks["cache"]
    cache_device.create_partitions([cache_part_size])
    cache_part = cache_device.partitions[0]
    error_device = ErrorDevice("error", cache_part)

    core_device = TestRun.disks["core"]
    core_device.create_partitions([cache_part_size] * cores_number)

    cache = casadm.start_cache(
        error_device, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True
    )
    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
    cache.set_cleaning_policy(CleaningPolicy.nop)

    cores = []
    for part in core_device.partitions:
        cores.append(cache.add_core(core_dev=part))

    return cache, cores, error_device, cache_part
