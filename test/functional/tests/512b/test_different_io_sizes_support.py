#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import datetime
import os

from core.test_run import TestRun
from api.cas import casadm
from storage_devices.disk import DiskType, DiskTypeSet
from api.cas.cache_config import CacheMode
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine


mountpoint = "/tmp/diff_io_size_support_test"
opencas_ioclass_conf_path = "/etc/opencas/ioclass-config.csv"
block_sizes = [1, 2, 4, 5, 8, 16, 32, 64, 128]


@pytest.mark.parametrizex("cache_mode", [CacheMode.WB, CacheMode.WT])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.nand]))
def test_support_different_io_size(cache_mode):
    """
    title: OpenCAS supports different IO sizes
    description: |
        OpenCAS supports IO of size in rage from 512b to 128K
    pass_criteria:
      - No IO errors
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_disk.create_partitions([Size(45, Unit.GibiByte)])

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0], cache_mode=cache_mode, force=True
        )
        core = cache.add_core(core_disk.partitions[0])

    with TestRun.step("Load the default ioclass config file"):
        cache.load_io_class(opencas_ioclass_conf_path)

    with TestRun.step("Create a filesystem on the core device and mount it"):
        fs_utils.remove(path=mountpoint, force=True, recursive=True, ignore_errors=True)
        fs_utils.create_directory(path=mountpoint)
        core.create_filesystem(Filesystem.xfs)
        core.mount(mountpoint)

    with TestRun.step(f"Run fio"):
        bs_list = [Size(x, Unit.KibiByte) for x in block_sizes]

        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .time_based()
            .do_verify()
            .direct()
            .read_write(ReadWrite.randwrite)
            .run_time(datetime.timedelta(seconds=1200))
            .io_depth(16)
            .verify_pattern(0xABCD)
        )

        for i, bs in enumerate(bs_list):
            fio_job = fio.add_job()
            fio_job.target(os.path.join(mountpoint, str(bs.value)))
            fio_job.block_size(bs)
            fio_job.file_size(Size((i + 1) * 200, Unit.MebiByte))

        fio_output = fio.run()

        fio_errors = fio_output[0].total_errors()
        if fio_errors != 0:
            TestRun.fail(f"fio errors: {fio_errors}, should equal 0")
