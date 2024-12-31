#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from type_def.size import Size, Unit


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_trim_stress(cache_mode, cache_line_size):
    """
        title: Trim support on cache devices in different cache modes stress test.
        description: |
          Stress test validating the ability of CAS to handle trim requests in different modes.
        pass_criteria:
          - No kernel bug.
          - Cache should still work correctly.
    """

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(1, Unit.GibiByte)] * 3)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
        cores = []
        for d in core_devices:
            cores.append(cache.add_core(d))

    with TestRun.step("Run I/O workload."):
        for _ in TestRun.iteration(range(1, 6)):
            run_fio([core.path for core in cores])

    with TestRun.step("Stop CAS."):
        for c in cores:
            c.remove_core()
        cache.stop()


def run_fio(paths):
    block_sizes = [f"{2 ** n}k" for n in range(0, 10)]

    fio = (
        Fio().create_command()
        .io_engine(IoEngine.libaio)
        .io_depth(16)
        .bs_split(":".join([f"{bs}/{100 // len(block_sizes)}" for bs in block_sizes]))
        .time_based()
        .run_time(timedelta(minutes=10))
        .trim_verify_zero()
        .verify_fatal()
    )

    for path, rw in zip(paths, [ReadWrite.trim, ReadWrite.randtrim, ReadWrite.trimwrite]):
        (
            fio.add_job(path + rw.name)
            .file_name(path)
            .read_write(rw)
        )

    fio.run(fio_timeout=timedelta(minutes=20))
