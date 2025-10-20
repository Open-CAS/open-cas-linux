#
# Copyright(c) 2023-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import math
import pytest

from api.cas.casadm import start_cache
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.memory import get_mem_free
from test_tools.os_tools import sync, drop_caches
from test_tools.udev import Udev
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_detach_memory_release():
    """
    title: Test for detecting if memory was released after detach operation.
    description: |
        Validate if ctx was released after detach operation.
    pass_criteria:
      - Memory used by cache device is released after detach operation.
      - No system crash.
    """

    with TestRun.step("Prepare disks"):
        cache_dev = TestRun.disks["cache"]
        if cache_dev.size < Size(100, Unit.GibiByte):
            TestRun.LOGGER.warning(
                f"To avoid false-positive scenarios it is better to use "
                f"cache disk greater than 100GiB. "
                f"Current cache device size: {cache_dev.size.get_value(Unit.GibiByte)}GiB"
            )
            cache_dev.create_partitions([cache_dev.size - Size(1, Unit.GibiByte)])
        else:
            cache_dev.create_partitions([Size(100, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]

        core_dev = TestRun.disks["core"]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Get RAM size before cache start"):
        sync()
        drop_caches()
        memory_before_cache_start = get_mem_free()

    with TestRun.step("Start cache and add core"):
        cache = start_cache(cache_dev, force=True)
        cache.add_core(core_dev)

    with TestRun.step("Detach cache"):
        cache.detach()
        sync()
        drop_caches()
        memory_after_detach = get_mem_free()

    with TestRun.step("Calculate memory usage"):
        metadata_released = math.isclose(
            memory_after_detach.get_value(),
            memory_before_cache_start.get_value(),
            rel_tol=0.1
        )

        if not metadata_released:
            TestRun.fail(
                f"Memory kept by ctx after detach operation\n"
                f"Memory before cache start: {memory_before_cache_start}\n"
                f"Memory after detach: {memory_after_detach}"
            )

        TestRun.LOGGER.info("Memory released successfully")
