#
# Copyright(c) 2023-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import time
import pytest
from datetime import timedelta

from api.cas.cache_config import CacheMode
from api.cas.casadm import start_cache
from core.test_run import TestRun
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from type_def.size import Size, Unit

mountpoint = "/mnt/cas"
test_file_path = f"{mountpoint}/test_file"
iterations_per_config = 10
cache_size = Size(16, Unit.GibiByte)
start_size = Size(512, Unit.Byte).get_value()
stop_size = Size(32, Unit.MegaByte).get_value()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_attach_detach_during_io(cache_mode):
    """
    title: Test for attach/detach cache during I/O.
    description: |
        Validate if attach and detach operation doesn't interrupt
        I/O on exported object
    pass_criteria:
      - No crash during attach and detach.
      - Detaching cache doesn't stop I/O on exported object.
      - Cache can be stopped after operations.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(40, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]

        cache_dev2 = TestRun.disks["cache2"]
        cache_dev2.create_partitions([Size(60, Unit.MebiByte), Size(100, Unit.MebiByte),
                                     Size(50, Unit.MebiByte), Size(80, Unit.MebiByte)])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step(f"Change cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    with TestRun.step("Run random mixed read and write workload"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.randrw)
            .run_time(timedelta(minutes=20))
            .time_based()
            .target(core.path)
            .blocksize_range([(start_size, stop_size)])
        )

        fio_pid = fio.run_in_background()
        time.sleep(5)

    with TestRun.step("Randomly detach and attach cache during I/O"):
        while TestRun.executor.check_if_process_exists(fio_pid):
            time.sleep(random.randint(2, 10))

            cache.detach()
            if cache.get_statistics().error_stats.cache.total != 0.0:
                TestRun.LOGGER.error(
                    f"Cache error(s) occurred after "
                    f"{cache_to_attach} detach"
                )
            time.sleep(5)

            cache_to_attach = random.choice(cache_dev2.partitions)
            cache.attach(device=cache_to_attach, force=True)
            if cache.get_statistics().error_stats.cache.total != 0.0:
                TestRun.LOGGER.error(
                    f"Cache error(s) occurred after "
                    f"{cache_to_attach} attach"
                )

    with TestRun.step("Check fio result after I/O finish."):
        TestRun.executor.wait_cmd_finish(fio_pid)
        fio_output = TestRun.executor.run(f"cat {fio.fio.fio_file}")
        fio_errors = fio.get_results(fio_output.stdout)[0].total_errors()
        if fio_output.exit_code != 0 and fio_errors != 0:
            TestRun.fail("Fio error(s) occurred!")
