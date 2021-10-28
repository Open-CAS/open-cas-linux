#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, ErrorFilter, VerifyMethod
from test_tools.device_mapper import ErrorDevice, DmTable
from core.test_run import TestRun
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    SeqCutOffPolicy,
    CleaningPolicy,
)
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("io_dir", [ReadWrite.randread, ReadWrite.randwrite])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_device_error(io_dir, cache_mode, cache_line_size):
    """
        title: Check if CAS behaves correctly when encountering errors on core device
        description: |
          Perform I/O on two exported objects created using error and non-error device.
          Validate CAS that stats counting is consistent with OS reporting.
          Also, check if normal I/O is uninterrupted and no DC occurs on any of the
          core devices.
        pass_criteria:
          - I/O error count in FIO and in cache statistics match
          - Positively passed fio verify on both core devices
    """
    with TestRun.step("Prepare error device and setup cache and cores"):
        cache, error_core, good_core = prepare_configuration(cache_mode, cache_line_size)

    good_core_fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .size(good_core.size)
        .block_size(cache_line_size)
        .target(good_core)
        .read_write(ReadWrite.randrw)
        .verify_pattern()
        .verify(VerifyMethod.pattern)
        .direct()
    )

    error_core_fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .size(error_core.size)
        .block_size(cache_line_size)
        .target(error_core)
        .read_write(io_dir)
        .continue_on_error(ErrorFilter.io)
        .direct()
    )
    if io_dir == ReadWrite.randwrite:
        error_core_fio.verify_pattern().verify(VerifyMethod.pattern)

    with TestRun.step("Run fio on core without errors in background"):
        fio_pid = good_core_fio.run_in_background()

    with TestRun.step("Run fio on error core and check if IO errors are present"):
        fio_errors = error_core_fio.run()[0].total_errors()

        if fio_errors == 0:
            TestRun.fail("No I/O ended with error!")

    with TestRun.step("Check error statistics on error core"):
        stats = cache.get_statistics()

        core_errors_in_cache = stats.error_stats.core.total
        if fio_errors != core_errors_in_cache:
            TestRun.fail(
                f"Core errors in cache stats({core_errors_in_cache}) should be equal to number of"
                " fio errors ({fio_errors})"
            )

    with TestRun.step("Wait for fio on good core"):
        TestRun.executor.wait_cmd_finish(fio_pid)

    with TestRun.step("Check error statistics on good core"):
        stats = good_core.get_statistics()

        if stats.error_stats.core.total != 0:
            TestRun.fail(
                f"No errors should be reported for good core. "
                "Actual result: {stats.error_stats.total}"
            )

    with TestRun.step("Stop the cache"):
        cache.stop()

    with TestRun.step("Verify error core device contents (if writes)"):
        if io_dir == ReadWrite.randwrite:
            error_core_fio.target(error_core.core_device).verify_only().run()

    with TestRun.step("Verify good core device contents"):
        good_core_fio.target(good_core.core_device).verify_only().run()


def prepare_configuration(cache_mode, cache_line_size):
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    cache_device.create_partitions([Size(70, Unit.MebiByte)])
    core_device.create_partitions(
        [Size(70, Unit.MebiByte), Size(70, Unit.MebiByte)]
    )
    core1 = core_device.partitions[0]
    core2 = core_device.partitions[1]

    error_device = ErrorDevice(
        "error",
        core1,
        DmTable.uniform_error_table(
            start_lba=0,
            stop_lba=int(core1.size.get_value(Unit.Blocks512)),
            num_error_zones=100,
            error_zone_size=Size(5, Unit.Blocks512),
        ).fill_gaps(core1),
    )

    cache = casadm.start_cache(
        cache_device.partitions[0],
        cache_mode=cache_mode,
        cache_line_size=cache_line_size,
        force=True,
    )
    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    cache.set_cleaning_policy(CleaningPolicy.nop)

    Udev.disable()
    error_core = cache.add_core(core_dev=error_device)
    good_core = cache.add_core(core_dev=core2)

    return cache, error_core, good_core
