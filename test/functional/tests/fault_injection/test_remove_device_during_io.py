#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time

import pytest

from datetime import timedelta
from api.cas import cli, casadm
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_core_during_io():
    """
        title: Test for removing core device during IO.
        description: |
          Creating CAS device, running fio on it and checking
          if core can be removed during IO operations.
        pass_criteria:
          - Core device is not removed.
    """
    with TestRun.step("Start cache and add core"):
        cache, core = prepare()

    with TestRun.step("Running 'fio'"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(4, Unit.KibiByte))
            .read_write(ReadWrite.randrw)
            .target(f"{core.path}")
            .direct(1)
            .run_time(timedelta(minutes=4))
            .time_based()
        )
        fio_pid = fio.run_in_background()
        time.sleep(10)

    with TestRun.step("Try to remove core during 'fio'"):
        TestRun.executor.run_expect_fail(
            cli.remove_core_cmd(f"{core.cache_id}", f"{core.core_id}")
        )

    with TestRun.step("Stopping 'fio'"):
        TestRun.executor.kill_process(fio_pid)

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_cache_during_io():
    """
        title: Test for stopping cache during IO.
        description: |
          Creating CAS device, running fio on it and checking
          if cache can be stopped during IO operations.
        pass_criteria:
          - Cache is not stopped.
    """
    with TestRun.step("Start cache and add core"):
        cache, core = prepare()

    with TestRun.step("Running 'fio'"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(4, Unit.KibiByte))
            .read_write(ReadWrite.randrw)
            .target(f"{core.path}")
            .direct(1)
            .run_time(timedelta(minutes=4))
            .time_based()
        )
        fio_pid = fio.run_in_background()
        time.sleep(10)

    with TestRun.step("Try to stop cache during 'fio'"):
        TestRun.executor.run_expect_fail(cli.stop_cmd(f"{cache.cache_id}"))

    with TestRun.step("Stopping 'fio'"):
        TestRun.executor.kill_process(fio_pid)

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()


def prepare():
    cache_dev = TestRun.disks["cache"]
    cache_dev.create_partitions([Size(2, Unit.GibiByte)])
    core_dev = TestRun.disks["core"]
    core_dev.create_partitions([Size(1, Unit.GibiByte)])
    cache = casadm.start_cache(cache_dev.partitions[0], force=True)
    core = cache.add_core(core_dev.partitions[0])
    return cache, core
