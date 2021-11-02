#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import time
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from test_utils.os_utils import Udev, sync
from test_utils.size import Size, Unit

io_size = Size(10000, Unit.Blocks4096)


@pytest.mark.parametrize(
    "cache_mode",
    [
        (CacheMode.WT, CacheMode.WB),
        (CacheMode.WB, CacheMode.PT),
        (CacheMode.WB, CacheMode.WT),
        (CacheMode.PT, CacheMode.WT),
        (CacheMode.WT, CacheMode.WA),
        (CacheMode.WT, CacheMode.WO),
        (CacheMode.WB, CacheMode.WO),
        (CacheMode.PT, CacheMode.WO),
        (CacheMode.WA, CacheMode.WO),
        (CacheMode.WO, CacheMode.WT),
        (CacheMode.WO, CacheMode.WB),
        (CacheMode.WO, CacheMode.PT),
        (CacheMode.WO, CacheMode.WA),
    ],
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_stop_and_load(cache_mode):
    """
        title: Test for stopping and loading cache back with dynamic cache mode switching.
        description: |
          Validate the ability of the CAS to switch cache modes at runtime and
          check if all of them are working properly after switching and
          after stopping and reloading cache back.
          Check also other parameters consistency after reload.
        pass_criteria:
          - In all cache modes data reads and writes are handled properly before and after reload.
          - All cache parameters preserve their values after reload.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(f"Start cache in {cache_mode[0]} mode"):
        cache = casadm.start_cache(cache_dev, cache_mode[0], force=True)
        Udev.disable()

    with TestRun.step("Add core to the cache"):
        core = cache.add_core(core_dev)

    with TestRun.step(f"Change cache mode to {cache_mode[1]}"):
        cache.set_cache_mode(cache_mode[1], flush=True)
        check_cache_config = cache.get_cache_config()

    with TestRun.step(f"Check if {cache_mode[1]} cache mode works properly"):
        check_cache_mode_operation(cache, core, cache_mode[1])

    with TestRun.step("Stop and load cache back"):
        cache.stop()
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Check parameters consistency"):
        if check_cache_config != cache.get_cache_config():
            failed_params = ""
            if check_cache_config.cache_mode != cache.get_cache_mode():
                failed_params += (
                    f"Cache mode is: {check_cache_config.cache_mode}, "
                    f"should be: {cache.get_cache_mode()}\n"
                )
            if check_cache_config.cleaning_policy != cache.get_cleaning_policy():
                failed_params += (
                    f"Cleaning policy is: {check_cache_config.cleaning_policy}, "
                    f"should be: {cache.get_cleaning_policy()}\n"
                )
            if check_cache_config.cache_line_size != cache.get_cache_line_size():
                failed_params += (
                    f"Cache line size is: {check_cache_config.cache_line_size}, "
                    f"should be: {cache.get_cache_line_size()}\n"
                )
            TestRun.fail(f"Parameters do not match after reload:\n{failed_params}")

    with TestRun.step(
        f"Check if {cache_mode[1]} cache mode works properly after reload"
    ):
        if cache_mode[1] == CacheMode.WA or cache_mode[1] == CacheMode.WO:
            check_separated_read_write_after_reload(cache, core, cache_mode[1], io_size)
        else:
            check_cache_mode_operation(cache, core, cache_mode[1])

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()
        Udev.enable()


@pytest.mark.parametrize(
    "cache_mode_1,cache_mode_2,flush",
    [
        (CacheMode.WT, CacheMode.WB, False),
        (CacheMode.WB, CacheMode.PT, False),
        (CacheMode.WB, CacheMode.PT, True),
        (CacheMode.WB, CacheMode.WT, False),
        (CacheMode.WB, CacheMode.WT, True),
        (CacheMode.PT, CacheMode.WT, False),
        (CacheMode.WT, CacheMode.WA, False),
        (CacheMode.WT, CacheMode.WO, False),
        (CacheMode.WB, CacheMode.WO, False),
        (CacheMode.WB, CacheMode.WO, True),
        (CacheMode.PT, CacheMode.WO, False),
        (CacheMode.WA, CacheMode.WO, False),
        (CacheMode.WO, CacheMode.WT, False),
        (CacheMode.WO, CacheMode.WT, True),
        (CacheMode.WO, CacheMode.WB, False),
        (CacheMode.WO, CacheMode.WB, True),
        (CacheMode.WO, CacheMode.PT, False),
        (CacheMode.WO, CacheMode.PT, True),
        (CacheMode.WO, CacheMode.WA, False),
        (CacheMode.WO, CacheMode.WA, True),
    ],
)
@pytest.mark.parametrize("io_mode", [ReadWrite.randwrite, ReadWrite.randrw])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_mode_switching_during_io(cache_mode_1, cache_mode_2, flush, io_mode):
    """
        title: Test for dynamic cache mode switching during IO.
        description: |
          Validate the ability of CAS to switch cache modes
          during working IO on CAS device.
        pass_criteria:
          - Cache mode is switched without errors.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(f"Start cache in {cache_mode_1} mode"):
        cache = casadm.start_cache(cache_dev, cache_mode_1, force=True)

    with TestRun.step("Add core to the cache"):
        core = cache.add_core(core_dev)

    with TestRun.step("Run 'fio'"):
        fio = (
            fio_prepare(core, io_mode)
            .verify(VerifyMethod.sha1)
            .run_time(timedelta(minutes=4))
            .time_based()
        )
        fio_pid = fio.run_in_background()
        time.sleep(5)

    with TestRun.step(
        f"Change cache mode to {cache_mode_2} with flush cache option set to: {flush}"
    ):
        cache_mode_switch_output = cache.set_cache_mode(cache_mode_2, flush)
        if cache_mode_switch_output.exit_code != 0:
            TestRun.fail("Cache mode switch failed!")

    with TestRun.step(f"Check if cache mode has switched properly during IO"):
        cache_mode_after_switch = cache.get_cache_mode()
        if cache_mode_after_switch != cache_mode_2:
            TestRun.fail(
                f"Cache mode did not switch properly! "
                f"Cache mode after switch is: {cache_mode_after_switch}, "
                f"should be: {cache_mode_2}"
            )

    with TestRun.step("Stop 'fio'"):
        TestRun.executor.kill_process(fio_pid)

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()


def storage_prepare():
    cache_dev = TestRun.disks["cache"]
    cache_dev.create_partitions([Size(1, Unit.GibiByte)])
    core_dev = TestRun.disks["core"]
    core_dev.create_partitions([Size(2, Unit.GibiByte)])
    return cache_dev.partitions[0], core_dev.partitions[0]


def check_cache_mode_operation(cache, core, cache_mode):
    cache.reset_counters()

    if cache_mode == CacheMode.WT:
        io_mode = ReadWrite.randwrite
        run_io_and_verify(cache, core, io_mode)

    if cache_mode == CacheMode.WB or cache_mode == CacheMode.PT:
        io_mode = ReadWrite.randrw
        run_io_and_verify(cache, core, io_mode)

    if cache_mode == CacheMode.WA or cache_mode == CacheMode.WO:
        io_mode = ReadWrite.randread
        run_io_and_verify(cache, core, io_mode)
        cache.reset_counters()
        io_mode = ReadWrite.randwrite
        run_io_and_verify(cache, core, io_mode)


def run_io_and_verify(cache, core, io_mode):
    fio_prepare(core, io_mode).run()
    sync()
    cache_mode = cache.get_cache_mode()
    cache_stats = cache.get_statistics()
    core_stats = core.get_statistics()

    if cache_mode == CacheMode.WB:
        if (
            core_stats.block_stats.core.writes.value != 0
            or core_stats.block_stats.exp_obj.writes.value <= 0
        ):
            TestRun.fail(
                "Write-Back cache mode is not working properly! "
                "There should be some writes to CAS device and none to the core."
            )

    if cache_mode == CacheMode.PT:
        if (
            cache_stats.block_stats.cache.writes.value != 0
            or cache_stats.block_stats.cache.reads.value != 0
        ):
            TestRun.fail(
                "Pass-Through cache mode is not working properly! "
                "There should be no reads or writes from/to cache."
            )

    if cache_mode == CacheMode.WT:
        if cache_stats.block_stats.cache != cache_stats.block_stats.core:
            TestRun.fail(
                "Write-Through cache mode is not working properly! "
                "'cache writes' and 'core writes' counts should be the same."
            )

    if cache_mode == CacheMode.WA:
        if io_mode == ReadWrite.randread:
            if (
                cache_stats.block_stats.cache.writes != io_size
                or cache_stats.block_stats.core.reads != io_size
            ):
                TestRun.fail(
                    "Write-Around cache mode is not working properly for data reads! "
                    "'cache writes' and 'core reads' should equal total data reads."
                )
        if io_mode == ReadWrite.randwrite:
            if cache_stats.block_stats.cache.writes != io_size:
                TestRun.fail(
                    "Write-Around cache mode is not working properly for data writes! "
                    "There should be no writes to cache since previous read operation."
                )

    if cache_mode == CacheMode.WO:
        if io_mode == ReadWrite.randread:
            if (
                cache_stats.block_stats.cache.writes.value != 0
                or cache_stats.block_stats.cache.reads.value != 0
            ):
                TestRun.fail(
                    "Write-Only cache mode is not working properly for data reads! "
                    "There should be no reads or writes from/to cache."
                )
        if io_mode == ReadWrite.randwrite:
            if (
                core_stats.block_stats.core.writes.value != 0
                or core_stats.block_stats.exp_obj.writes != io_size
            ):
                TestRun.fail(
                    "Write-Only cache mode is not working properly for data writes! "
                    "All writes should be passed to CAS device and none to the core."
                )


def check_separated_read_write_after_reload(cache, core, cache_mode, io_size):
    # io_size_after_reload should be set to a greater value then global io_size value
    io_size_after_reload = Size(12000, Unit.Blocks4096)
    if io_size_after_reload <= io_size:
        TestRun.fail(
            "io_size_after_reload value is not greater then global io_size value!"
        )

    io_mode = ReadWrite.randread
    fio_prepare(core, io_mode, io_size_after_reload).run()
    sync()
    cache_stats = cache.get_statistics()
    io_new_data = io_size_after_reload - io_size

    if cache_mode == CacheMode.WA:
        if (
            cache_stats.block_stats.cache.writes != io_new_data
            or cache_stats.block_stats.core.reads != io_new_data
        ):
            TestRun.fail(
                "Write-Around cache mode is not working properly for data reads after reload! "
                "'cache writes' and 'core reads' should equal "
                "the difference from previous data reads."
            )
    if cache_mode == CacheMode.WO:
        if (
            cache_stats.block_stats.cache.writes.value != 0
            or cache_stats.block_stats.cache.reads != io_size
        ):
            TestRun.fail(
                "Write-Only cache mode is not working properly for data reads after reload! "
                "There should be no writes to cache and reads "
                "from cache should equal previous writes to it."
            )

    cache.reset_counters()
    io_mode = ReadWrite.randwrite
    fio_prepare(core, io_mode, io_size_after_reload).run()
    sync()
    cache_stats = cache.get_statistics()
    core_stats = core.get_statistics()

    if cache_mode == CacheMode.WA:
        if cache_stats.block_stats.cache.writes != io_size_after_reload:
            TestRun.fail(
                "Write-Around cache mode is not working properly for data writes after reload! "
                "There should be no writes to cache since previous read operation."
            )
    if cache_mode == CacheMode.WO:
        if (
            core_stats.block_stats.core.writes.value != 0
            or core_stats.block_stats.exp_obj.writes != io_size_after_reload
        ):
            TestRun.fail(
                "Write-Only cache mode is not working properly for data writes after reload! "
                "All writes should be passed to CAS device and none to the core."
            )


def fio_prepare(core, io_mode, io_size=io_size):
    fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .size(io_size)
        .read_write(io_mode)
        .target(core.path)
        .direct(1)
    )
    return fio
