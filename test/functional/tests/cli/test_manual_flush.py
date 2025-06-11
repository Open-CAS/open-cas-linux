#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import time

from core.test_run_utils import TestRun
from storage_devices.device import Device
from type_def.size import Size, Unit
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy
from test_tools.udev import Udev


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_manual_flush():
    """
    title: Test for manual cache and core flushing
    description: |
        The test is to see if dirty data will be removed from the cache
        or core after using the casadm command with the corresponding parameter.
    pass_criteria:
        - Cache and core are filled with dirty data.
        - After cache and core flush dirty data are cleared.
    """
    cache_id = 1

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache and set cleaning policy to NOP"):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
        core = cache.add_core(core_dev)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Populate cache with dirty data."):
        write_dirty_data(Size(1, Unit.MiB), core, cache_id)
        if cache.get_dirty_blocks() <= Size.zero():
            TestRun.fail("Failed to populate Cache with dirty data")
        if core.get_dirty_blocks() <= Size.zero():
            TestRun.fail("There is no dirty data on Core")

    with TestRun.step("Perform casadm command and check whether dirty data is cleared from core"):
        core.flush_core()
        if core.get_dirty_blocks() > Size.zero():
            TestRun.fail("Dirty data has not been cleaned from core")

    with TestRun.step("Populate cache with dirty data again."):
        write_dirty_data(Size(1, Unit.MiB), core, cache_id)
        if core.get_dirty_blocks() <= Size.zero():
            TestRun.fail("Cache has not been populated with dirty data.")

    with TestRun.step("Perform casadm command to flush cache"):
        cache.flush_cache()
    with TestRun.step("Check if dirty data are cleared in stats"):
        if cache.get_dirty_blocks() > Size.zero():
            TestRun.fail("Cache contain dirty data.")


def write_dirty_data(size: Size, core: Device, dev_id: int):
    fio = (
        Fio()
        .create_command()
        .size(size)
        .read_write(ReadWrite.randwrite)
        .io_engine(IoEngine.libaio)
        .block_size(Size(1, Unit.Blocks4096))
    )
    fio.add_job(f"core{dev_id}").target(core.path)
    fio.run()
    time.sleep(1)
