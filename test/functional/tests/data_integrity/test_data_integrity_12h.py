#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import datetime

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Unit, Size


start_size = int(Size(512, Unit.Byte))
step = int(Size(512, Unit.Byte))
stop_size = int(Size(128, Unit.KibiByte))
runtime = datetime.timedelta(hours=12) / (stop_size / 512)


@pytest.mark.os_dependent
@pytest.mark.parametrize("cache_mode", [CacheMode.WT, CacheMode.WB])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_data_integrity_12h(cache_mode):
    """
    title: Data integrity test in passed cache mode with duration time equal to 12h
        description: Create 1 cache with size between 40MB and 50MB and 1 core with size 150MB
        pass_criteria:
            - System does not crash.
            - All operations complete successfully.
            - Data consistency is being preserved.
    """
    with TestRun.step(f"Prepare cache instance in {cache_mode} cache mode"):
        cache, core = prepare(cache_mode)

    with TestRun.step("Fill cache"):
        fill_cache(core.path)

    with TestRun.step("Run test workloads with verification"):
        run_workload(core.path)


def prepare(cache_mode):
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']

    cache_device.create_partitions([Size(random.randint(40, 50), Unit.MebiByte)])
    core_device.create_partitions([Size(150, Unit.MebiByte)])

    cache_device = cache_device.partitions[0]
    core_device = core_device.partitions[0]

    TestRun.LOGGER.info(f"Starting cache")
    cache = casadm.start_cache(cache_device, cache_mode, force=True)
    TestRun.LOGGER.info(f"Adding core device")
    core = casadm.add_core(cache, core_dev=core_device)

    return cache, core


def fill_cache(target):
    fio_run_fill = Fio().create_command()
    fio_run_fill.io_engine(IoEngine.libaio)
    fio_run_fill.direct()
    fio_run_fill.read_write(ReadWrite.write)
    fio_run_fill.io_depth(16)
    fio_run_fill.block_size(Size(1, Unit.MebiByte))
    fio_run_fill.target(target)
    fio_run_fill.run()


def run_workload(target):
    fio_run = Fio().create_command()
    fio_run.io_engine(IoEngine.libaio)
    fio_run.direct()
    fio_run.time_based()
    fio_run.do_verify()
    fio_run.verify(VerifyMethod.meta)
    fio_run.verify_dump()
    fio_run.run_time(runtime)
    fio_run.read_write(ReadWrite.randrw)
    fio_run.io_depth(128)
    fio_run.target(target)

    for block_size in range(start_size, stop_size + 1, step):
        fio_job = fio_run.add_job()
        fio_job.stonewall()
        fio_job.block_size(block_size)
        fio_run.verify_backlog(block_size)

    fio_run.run()
