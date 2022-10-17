#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from time import sleep

import pytest

from api.cas import casadm_parser
from api.cas.cache_config import CacheStatus
from api.cas.core import CoreStatus
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType
from test_utils.size import Size, Unit


@pytest.mark.CI
@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_simulation_startup_from_config():
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(4, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]
        cache_id, core_id = 1, 1

    with TestRun.step("prepare CAS config."):
        cache_config = InitConfig()
        cache_config.add_cache(cache_id, cache_dev)
        cache_config.add_core(cache_id, core_id, core_dev)
        cache_config.save_config_file()

    with TestRun.step("Initialize CAS from config."):
        TestRun.executor.run_expect_success(f"casctl init")

    with TestRun.step("Stop all CAS instances."):
        TestRun.executor.run_expect_success(f"casctl stop")

    with TestRun.step("Simulate boot process."):
        TestRun.executor.run_expect_success(f"udevadm trigger")
        sleep(1)

    with TestRun.step("Verify if cache is up and working."):
        cache = casadm_parser.get_caches()[0]
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(f"Cache {cache.cache_id} should be running but is {cache.get_status()}.")
        core = cache.get_core_devices()[0]
        if core.get_status() is not CoreStatus.active:
            TestRun.fail(f"Core {core.core_id} should be active but is {core.get_status()}.")
