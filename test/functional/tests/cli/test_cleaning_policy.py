#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import time

from core.test_run_utils import TestRun
from test_utils.size import Size, Unit
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy
from test_utils.os_utils import Udev


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policy():
    """
    Title: test_cleaning_policy
    description: |
        The test is to see if dirty data will be removed from the Cache after changing the
        cleaning policy from NOP to one that expects a flush.
    pass_criteria:
        - Cache is successfully populated with dirty data
        - Cleaning policy is changed successfully
        - There is no dirty data after the policy change
    """
    wait_time = 60

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_dev = cache_device.partitions[0]
        core_dev = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in Write-Back mode and set cleaning policy to NOP"):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Add core"):
        core = cache.add_core(core_dev)

    with TestRun.step("Populate cache with dirty data"):
        fio = (
            Fio()
            .create_command()
            .size(cache.size)
            .read_write(ReadWrite.randwrite)
            .io_engine(IoEngine.libaio)
            .block_size(Size(1, Unit.Blocks4096))
            .direct()
            .target(core.path)
        )
        fio.run()

        if cache.get_dirty_blocks() <= Size.zero():
            TestRun.fail("Cache does not contain dirty data")

    with TestRun.step("Change cleaning policy"):
        cache.set_cleaning_policy(CleaningPolicy.acp)
        t_end = time.time() + wait_time
        while time.time() < t_end:
            time.sleep(1)
            if cache.get_dirty_blocks() == Size.zero():
                TestRun.LOGGER.info(
                    f"Cache flushed after {round(time.time() - (t_end - wait_time), 2)} seconds."
                )
                break

    with TestRun.step("Check if cache contains dirty data"):
        if cache.get_dirty_blocks() != Size.zero():
            TestRun.fail("There is dirty data on cache after changing cleaning policy")
