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
from test_tools.fio.fio_param import ReadWrite, IoEngine, ErrorFilter
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_soft_hot_plug_cache(cache_mode):
    """
        title: Test for soft hot plug of cache device.
        description: |
          Validate the ability of CAS to handle software hot plug
          of cache device during IO for different cache modes.
        pass_criteria:
          - CAS doesn't crash after unplugging cache device.
          - Appropriate errors in IO and cache/core stats depending on cache mode.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(2, Unit.GibiByte)])

    with TestRun.step(f"Start cache in {cache_mode} cache mode and add core"):
        cache = casadm.start_cache(cache_dev.partitions[0], cache_mode, force=True)
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Run 'fio'"):
        fio_cmd = fio_prepare(core)
        fio_pid = fio_cmd.run_in_background()
        time.sleep(10)

    with TestRun.step("Soft hot unplug cache device"):
        cache_dev.unplug()
        try:
            cache.get_status()
        except CmdException:
            TestRun.fail("CAS crashed after unplugging cache device!")

    with TestRun.step("Wait for 'fio' to finish..."):
        TestRun.executor.wait_cmd_finish(fio_pid)

    with TestRun.step("Check for appropriate cache, core and fio errors"):
        fio_output = TestRun.executor.run(f"cat {fio_cmd.fio.fio_file}")
        fio_errors = fio_cmd.get_results(fio_output.stdout)[0].total_errors()
        cache_stats = cache.get_statistics()
        cache_errors = cache_stats.error_stats.cache.total
        core_errors = cache_stats.error_stats.core.total

        failed_errors = ""
        if cache_mode == CacheMode.WB or cache_mode == CacheMode.WO:
            if fio_errors <= 0:
                failed_errors += f"fio errors: {fio_errors}, should be greater then 0\n"
        if cache_mode == CacheMode.WT or cache_mode == CacheMode.WA:
            if fio_errors != 0:
                failed_errors += f"fio errors: {fio_errors}, should equal 0\n"
            if cache_errors <= 0:
                failed_errors += f"cache errors: {cache_errors}, should be greater then 0\n"
        if cache_mode == CacheMode.PT:
            if fio_errors != 0:
                failed_errors += f"fio errors: {fio_errors}, should equal 0\n"
            if cache_errors != 0:
                failed_errors += f"cache errors: {cache_errors}, should equal 0\n"
        if core_errors != 0:
            failed_errors += f"core errors: {core_errors}, should equal 0\n"

        if failed_errors:
            TestRun.fail(
                f"There are some inconsistencies in error stats "
                f"for {cache_mode} cache mode:\n{failed_errors}"
            )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()

    with TestRun.step("Plug back cache device"):
        cache_dev.plug()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
def test_soft_hot_plug_core(cache_mode):
    """
        title: Test for soft hot plug of one core device.
        description: |
          Validate the ability of CAS to handle software hot plug
          of core device during IO for different cache modes.
        pass_criteria:
          - CAS doesn't crash after unplugging core device.
          - Appropriate errors in IO and cache/core stats depending on cache mode.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev_unplugged = TestRun.disks["core1"]
        core_dev_unplugged.create_partitions([Size(2, Unit.GibiByte)])
        core_dev_active = TestRun.disks["core2"]
        core_dev_active.create_partitions([Size(2, Unit.GibiByte)])

    with TestRun.step(f"Start cache in {cache_mode} cache mode and add 2 cores"):
        cache = casadm.start_cache(cache_dev.partitions[0], cache_mode, force=True)
        core_unplugged = cache.add_core(core_dev_unplugged.partitions[0])
        core_active = cache.add_core(core_dev_active.partitions[0])

    with TestRun.step("Run 'fio'"):
        fio_cmd_core_unplugged = fio_prepare(core_unplugged)
        # Wait a while before generating next fio command to prevent writing output
        # from both commands into the same file (time-based output filename).
        time.sleep(3)
        fio_cmd_core_active = fio_prepare(core_active)
        fio_pid_core_unplugged = fio_cmd_core_unplugged.run_in_background()
        fio_pid_core_active = fio_cmd_core_active.run_in_background()
        time.sleep(10)

    with TestRun.step("Soft hot unplug one core device"):
        core_dev_unplugged.unplug()
        try:
            cache.get_status()
        except CmdException:
            TestRun.fail("CAS crashed after unplugging core device!")

    with TestRun.step("Wait for 'fio' to finish..."):
        TestRun.executor.wait_cmd_finish(fio_pid_core_unplugged)
        TestRun.executor.wait_cmd_finish(fio_pid_core_active)

    with TestRun.step("Check for appropriate cache, core and fio errors"):
        fio_output_core_unplugged = TestRun.executor.run(
            f"cat {fio_cmd_core_unplugged.fio.fio_file}"
        )
        fio_output_core_active = TestRun.executor.run(
            f"cat {fio_cmd_core_active.fio.fio_file}"
        )
        fio_errors_core_unplugged = fio_cmd_core_unplugged.get_results(
            fio_output_core_unplugged.stdout
        )[0].total_errors()
        fio_errors_core_active = fio_cmd_core_active.get_results(
            fio_output_core_active.stdout
        )[0].total_errors()
        cas_errors_cache = cache.get_statistics().error_stats.cache.total
        cas_errors_core_unplugged = (
            core_unplugged.get_statistics().error_stats.core.total
        )
        cas_errors_core_active = core_active.get_statistics().error_stats.core.total

        failed_errors = ""
        if fio_errors_core_unplugged <= 0:
            failed_errors += (
                f"fio errors on unplugged core: {fio_errors_core_unplugged}, "
                f"should be greater then 0\n"
            )
        if fio_errors_core_active != 0:
            failed_errors += (
                f"fio errors on active core: {fio_errors_core_active}, should equal 0\n"
            )
        if cas_errors_cache != 0:
            failed_errors += (
                f"CAS errors on cache: {cas_errors_cache}, should equal 0\n"
            )
        if cas_errors_core_unplugged <= 0:
            failed_errors += (
                f"CAS errors on unlugged core: {cas_errors_core_unplugged}, "
                f"should be greater then 0\n"
            )
        if cas_errors_core_active != 0:
            failed_errors += (
                f"CAS errors on active core: {cas_errors_core_active}, should equal 0\n"
            )

        if failed_errors:
            TestRun.fail(
                f"There are some inconsistencies in error stats "
                f"for {cache_mode} cache mode:\n{failed_errors}"
            )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()

    with TestRun.step("Plug back core device"):
        core_dev_unplugged.plug()


def fio_prepare(core):
    fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.randrw)
        .target(core.path)
        .continue_on_error(ErrorFilter.io)
        .direct(1)
        .run_time(timedelta(seconds=120))
        .time_based()
    )
    return fio
