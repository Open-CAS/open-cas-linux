#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm_parser
from api.cas.cache_config import CacheStatus
from api.cas.cli import ctl_init, ctl_stop
from api.cas.core import CoreStatus
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType
from type_def.size import Size, Unit


@pytest.mark.CI
@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_simulation_startup_from_config():
    """
    title: Test for CAS initialization from a configuration file
    description: |
        Verify that CAS can be properly initialized from a configuration file and subsequently
        started correctly after udev trigger.
    pass_criteria:
      - Cache initialization from configuration file works properly
      - Cache is working after udev trigger
      - Core is working after udev trigger
    """

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(2, Unit.GibiByte)])
        core_device.create_partitions([Size(4, Unit.GibiByte)])

        cache_dev = cache_device.partitions[0]
        core_dev = core_device.partitions[0]

        cache_id, core_id = 1, 1

    with TestRun.step("Prepare CAS config"):
        cache_config = InitConfig()
        cache_config.add_cache(cache_id, cache_dev)
        cache_config.add_core(cache_id, core_id, core_dev)
        cache_config.save_config_file()

    with TestRun.step("Initialize cache from config"):
        TestRun.executor.run_expect_success(ctl_init())

    with TestRun.step("Verify if cache is working"):
        caches = casadm_parser.get_caches()
        if not caches:
            TestRun.fail("Cache is not working")
        cache = caches[0]
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(
                f"Cache {cache.cache_id} should be running but is in {cache.get_status()} "
                f"state."
            )

    with TestRun.step("Verify if core is working"):
        core = cache.get_cores()[0]
        if core.get_status() is not CoreStatus.active:
            TestRun.fail(
                f"Core {core.core_id} should be active but is in {core.get_status()} " f"state."
            )

    with TestRun.step("Stop cache instance using casctl"):
        TestRun.executor.run_expect_success(ctl_stop())

    with TestRun.step("Trigger udev"):
        TestRun.executor.run_expect_success(f"udevadm trigger")

    with TestRun.step("Verify if cache is working"):
        caches = casadm_parser.get_caches()
        if not caches:
            TestRun.fail("Cache is not working")
        cache = caches[0]
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(
                f"Cache {cache.cache_id} should be running but is in {cache.get_status()} "
                f"state."
            )

    with TestRun.step("Verify if core is working"):
        cores = cache.get_cores()
        if not cores:
            TestRun.fail("Core is not working")
        core = cores[0]
        if core.get_status() is not CoreStatus.active:
            TestRun.fail(
                f"Core {core.core_id} should be active but is in {core.get_status()} " f"state."
            )
