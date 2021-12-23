#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, CpusAllowedPolicy, ReadWrite
from test_utils.os_utils import get_dut_cpu_physical_cores
from test_utils.size import Size, Unit

mount_point = "/mnt/test"
runtime = timedelta(minutes=15)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("io_engine", [IoEngine.sync, IoEngine.libaio, IoEngine.psync,
                          IoEngine.vsync, IoEngine.pvsync, IoEngine.posixaio, IoEngine.mmap])
def test_io_engines(cache_mode, filesystem, io_engine):
    """
        title: FIO with data integrity check on CAS.
        description: |
          Run 15min FIO with data integrity check on CAS device using IO Engine
        pass_criteria:
          - Data integrity checked and correct after workload.
          - Cache stopping works properly.
    """
    with TestRun.step("Prepare CAS device according to configuration."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

        TestRun.LOGGER.info(f"Create filesystem '{filesystem}' on '{core_dev.path}'")
        core_dev.create_filesystem(filesystem)
        core = cache.add_core(core_dev)
        core.mount(mount_point)

    with TestRun.step("Run 15 minutes FIO with data integrity check on CAS device\n"
                      "using IO Engine from configuration."):
        TestRun.LOGGER.info(f"Tested configuration:\n"
                            f"cache mode: {cache_mode},\n"
                            f"file system: {filesystem}\n"
                            f"with io engine: {io_engine}")

        fio = (Fio()
               .create_command()
               .direct()
               .io_engine(io_engine)
               .run_time(runtime)
               .time_based()
               .target(f"{mount_point}/fio_file")
               .read_write(ReadWrite.randrw)
               .write_percentage(30)
               .verification_with_pattern()
               .size(Size(1, Unit.GibiByte))
               .cpus_allowed(get_dut_cpu_physical_cores())
               .cpus_allowed_policy(CpusAllowedPolicy.split))
        fio.run()
