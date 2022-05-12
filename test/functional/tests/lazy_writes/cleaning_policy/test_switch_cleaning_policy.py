#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta
from time import sleep

import pytest
from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.asynchronous import start_async_func
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_switch_cleaning_policy():
    """
        title: Dynamic Cleaning Policy Switching - IO reads/writes.
        description: Verify that cleaning policy switching works properly
                     during working IO on CAS device.
        pass_criteria:
          - cleaning policy switching properly
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(100, Unit.MebiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(400, Unit.MebiByte)])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Start cache in Write-Back mode and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
        cache.set_cleaning_policy(CleaningPolicy.alru)
        core = cache.add_core(core_dev)

    with TestRun.step("Start fio on OpenCAS device."):
        fio = Fio().create_command() \
            .time_based() \
            .run_time(timedelta(minutes=15)) \
            .read_write(ReadWrite.readwrite) \
            .block_size(Size(1, Unit.Blocks4096)) \
            .direct() \
            .io_engine(IoEngine.libaio) \
            .target(core.path)
        fio_task = start_async_func(fio.fio.run)

    while fio_task.done() is False:
        for policy in CleaningPolicy:

            with TestRun.step(f"Change cleaning policy type to {policy}."):
                cache.set_cleaning_policy(policy)

                TestRun.LOGGER.info("Check cleaning policy type.")
                current_policy = cache.get_cleaning_policy()
                if current_policy != policy:
                    TestRun.fail(f"Cleaning policy should be: {policy}. Current: {current_policy}.")

                TestRun.LOGGER.info("Wait 5 seconds.")
                sleep(5)

    with TestRun.step("Check fio result."):
        fio_result = fio_task.result()
        if fio_result.exit_code != 0:
            TestRun.fail("Fio ended with an error!")
