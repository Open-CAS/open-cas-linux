#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from time import sleep

from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, ErrorFilter
from test_tools.device_mapper import DmTable
from storage_devices.error_device import ErrorDevice
from core.test_run import TestRun
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    SeqCutOffPolicy,
    CleaningPolicy,
    CacheModeTrait,
)
from storage_devices.disk import DiskTypeSet, DiskType
from test_utils.io_stats import IoStats
from type_def.size import Size, Unit


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd4k, DiskType.hdd]))
def test_error_device_as_cache_clean_wt(cache_line_size):
    """
    title: Validate Open CAS ability to handle read hit I/O error on cache device for clean data
    description: |
        Perform I/O on exported object in Write-Through mode while error device is cache device and
        validate if errors are present in Open CAS stats.
    pass_criteria:
      - Write error count in io is zero
      - Read error count in io is zero
      - Write error count in cache statistics is zero
      - Total error count in cache statistics is greater than zero
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(400, Unit.MebiByte)])

        cache_part = cache_device.partitions[0]
        error_device = ErrorDevice("error", cache_part)

    with TestRun.step("Start cache in Write-Through mode"):
        cache = casadm.start_cache(
            error_device, cache_mode=CacheMode.WT, cache_line_size=cache_line_size, force=True
        )

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step(f"Add core"):
        core = cache.add_core(core_dev=core_device.partitions[0])

    with TestRun.step("Run fio against core to fill it with pattern"):
        fio = (
            Fio()
            .create_command()
            .target(core)
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randwrite)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no errors"):
        if fio_errors != 0:
            TestRun.fail("Fio reported errors!")

    with TestRun.step("Stop cache"):
        metadata_size = cache.get_metadata_size_on_disk() + Size(1, Unit.MiB)
        cache.stop()

    with TestRun.step("Enable errors on cache device (after metadata area)"):
        error_device.change_table(
            error_table(start_lba=metadata_size, stop_lba=cache_part.size).fill_gaps(cache_part)
        )

    with TestRun.step("Load cache and reset counters"):
        cache = casadm.load_cache(error_device)
        cache.reset_counters()

    with TestRun.step("Run io against core with pattern verification"):
        fio = (
            Fio()
            .create_command()
            .target(core)
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randread)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no errors"):
        if fio_errors != 0:
            TestRun.fail("Fio reported errors!")

    with TestRun.step("Check cache error statistics"):
        stats = cache.get_statistics()
        write_errors_in_cache = stats.error_stats.cache.writes
        if write_errors_in_cache != 0:
            TestRun.fail(f"Write errors in cache stats detected ({write_errors_in_cache})!")

        total_errors_in_cache = stats.error_stats.cache.total
        if total_errors_in_cache == 0:
            TestRun.fail(
                f"Total errors in cache stats ({total_errors_in_cache}) should be greater than 0!"
            )

        TestRun.LOGGER.info(f"Total number of I/O errors in cache stats: {total_errors_in_cache}")


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd4k, DiskType.hdd]))
def test_error_device_as_cache_clean_wa(cache_line_size):
    """
    title: Validate Open CAS ability to handle read hit I/O error on cache device for clean data
    description: |
        Perform I/O on exported object in Write-Around mode while error device is cache device and
        validate if errors are present in Open CAS stats.
    pass_criteria:
      - Write error count in io is zero
      - Read error count in io is zero
      - Read error count in cache statistics is zero
      - Total error count in cache statistics is greater than zero
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(400, Unit.MebiByte)])

        cache_part = cache_device.partitions[0]
        error_device = ErrorDevice("error", cache_part)

    with TestRun.step("Start cache in Write-Around"):
        cache = casadm.start_cache(
            error_device, cache_mode=CacheMode.WA, cache_line_size=cache_line_size, force=True
        )

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step(f"Add core"):
        core = cache.add_core(core_dev=core_device.partitions[0])

    with TestRun.step("Run fio against core to fill it with pattern"):
        fio = (
            Fio()
            .create_command()
            .target(core)
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randread)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no errors"):
        if fio_errors != 0:
            TestRun.fail("Fio reported errors!")

    with TestRun.step("Stop cache"):
        metadata_size = cache.get_metadata_size_on_disk() + Size(1, Unit.MiB)
        cache.stop()

    with TestRun.step("Enable errors on cache device (after metadata area)"):
        error_device.change_table(
            error_table(start_lba=metadata_size, stop_lba=cache_part.size).fill_gaps(cache_part)
        )

    with TestRun.step("Load cache and reset counters"):
        cache = casadm.load_cache(error_device)
        cache.reset_counters()

    with TestRun.step("Run io against core with pattern verification"):
        fio = (
            Fio()
            .create_command()
            .target(core)
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randwrite)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no errors"):
        if fio_errors != 0:
            TestRun.fail("Fio reported errors!")

    with TestRun.step("Check cache error statistics"):
        stats = cache.get_statistics()
        read_errors_in_cache = stats.error_stats.cache.reads
        if read_errors_in_cache != 0:
            TestRun.fail(f"Reads errors in cache stats detected ({read_errors_in_cache})!")

        total_errors_in_cache = stats.error_stats.cache.total
        if total_errors_in_cache == 0:
            TestRun.fail(
                f"Total errors in cache stats ({total_errors_in_cache}) should be greater than 0!"
            )

        TestRun.LOGGER.info(f"Total number of I/O errors in cache stats: {total_errors_in_cache}")


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

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(400, Unit.MebiByte)] * 2)

        cache_part = cache_device.partitions[0]
        core_parts = core_device.partitions
        error_device = ErrorDevice("error", cache_part)

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            error_device, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True
        )

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step(f"Add core"):
        cores = [cache.add_core(core_dev=core) for core in core_parts]

    with TestRun.step("Run io against the first core to fill it with pattern"):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randwrite)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported no errors"):
        if fio_errors != 0:
            TestRun.fail("Fio reported errors!")

    with TestRun.step("Stop cache"):
        cache.stop(no_data_flush=True)

    with TestRun.step("Enable errors on cache device (after metadata area)"):
        metadata_size = cache.get_metadata_size_on_disk() + Size(1, Unit.MiB)
        error_device.change_table(
            error_table(start_lba=metadata_size, stop_lba=cache_part.size).fill_gaps(cache_part)
        )

    with TestRun.step("Load cache and reset counters"):
        cache = casadm.load_cache(error_device)
        cache.reset_counters()

    with TestRun.step("Run fio against the first core with pattern verification"):
        fio = (
            Fio()
            .create_command()
            .target(cores[0])
            .io_engine(IoEngine.libaio)
            .io_depth(1)
            .num_jobs(1)
            .size(cache_part.size)
            .read_write(ReadWrite.randread)
            .block_size(cache_line_size)
            .rand_seed(int(cache_part.size.get_value()))
            .direct()
            .verification_with_pattern("0xabcd")
            .do_verify(False)
            .continue_on_error(ErrorFilter.io)
        )
        fio_errors = fio.run()[0].total_errors()

    with TestRun.step("Check if fio reported errors"):
        if fio_errors == 0:
            TestRun.fail("Fio does not reported read errors!")
        TestRun.LOGGER.info(f"Number of fio read errors: {fio_errors}")

    with TestRun.step("Check the second core I/O traffic"):
        core_2_errors_before = IoStats.get_io_stats(cores[1].get_device_id())
        sleep(5)
        core_2_errors_after = IoStats.get_io_stats(cores[1].get_device_id())

        if (
            core_2_errors_after.reads > core_2_errors_before.reads
            or core_2_errors_after.writes > core_2_errors_before.writes
        ):
            TestRun.fail(f"I/O traffic detected on the second core ({cores[1]})!")
        else:
            TestRun.LOGGER.info(f"I/O traffic stopped on the second core ({cores[1]})")

    with TestRun.step("Check total cache error statistics"):
        stats = cache.get_statistics()
        total_errors_in_cache = stats.error_stats.cache.total
        if total_errors_in_cache == 0:
            TestRun.fail(
                f"Total errors in cache stats ({total_errors_in_cache}) should be greater than 0!"
            )
        TestRun.LOGGER.info(f"Total number of I/O errors in cache stats: {total_errors_in_cache}")


def error_table(start_lba: Size, stop_lba: Size):
    return DmTable.uniform_error_table(
        start_lba=int(start_lba.get_value(Unit.Blocks512)),
        stop_lba=int(stop_lba.get_value(Unit.Blocks512)),
        num_error_zones=100,
        error_zone_size=Size(5, Unit.Blocks512),
    )
