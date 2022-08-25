#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from time import sleep

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheStatus
from api.cas.core import CoreStatus
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType
from test_utils.size import Size, Unit


@pytest.mark.CI
@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_incremental_load_basic():
    """
        title: Incremental load test basic
        description: |
            Test incremental load and core pool functionality
        pass_criteria:
          - cores after start and load should be in active state and cache in running state
          - cores after adding to core pool are in inactive state and cache in incomplete state
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(4, Unit.GibiByte)] * 3)
        core_devs = core_disk.partitions
        cache_id = 1
        core_ids = [1, 2, 3]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, cache_id=cache_id)
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(f"Cache {cache.core_id} should be running but is {cache.get_status()}.")

    with TestRun.step("Add cores."):
        for core_dev in core_devs:
            core = cache.add_core(core_dev)
            if core.get_status() is not CoreStatus.active:
                TestRun.fail(f"Core {core.core_id} should be active but is {core.get_status()}.")

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Add cores to core pool."):
        cores = []
        for core_dev, core_id in zip(core_devs, core_ids):
            core = casadm.try_add(core_device=core_dev, cache_id=cache_id, core_id=core_id)
            cores.append(core)
            if core.get_status() is not CoreStatus.detached:
                TestRun.fail(f"Core {core.core_id} should be detached but is {core.get_status()}.")

    with TestRun.step("Load cache"):
        cache = casadm.load_cache(cache_dev)
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(f"Cache {cache.cache_id} should be running but is {cache.get_status()}.")
        for core in cores:
            if core.get_status() is not CoreStatus.active:
                TestRun.fail(f"Core {core.core_id} should be active but is {core.get_status()}.")


@pytest.mark.CI
@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_incremental_load_hidden_core():
    """
        title: Incremental load test with hidden core
        description: |
            Test incremental load and core pool functionality with hidden core partition
        pass_criteria:
          - cores after adding to core pool are in detached state
          - visible cores after start and load should be in active state
          - hidden core after load should be in detached state
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(4, Unit.GibiByte)] * 3)
        core_devs = core_disk.partitions
        cache_id = 1

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, cache_id=cache_id)
        if cache.get_status() is not CacheStatus.running:
            TestRun.fail(f"Cache {cache.core_id} should be running but is {cache.get_status()}.")

    with TestRun.step("Add cores."):
        for core_dev in core_devs:
            core = cache.add_core(core_dev)
            if core.get_status() is not CoreStatus.active:
                TestRun.fail(f"Core {core.core_id} should be active but is {core.get_status()}.")
        hidden_core = cache.get_core_devices()[2]

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Hide core part form from being loaded"):
        core_disk.remove_partitions()
        core_disk.create_partitions([Size(4, Unit.GibiByte)] * 2)

    with TestRun.step("Load cache"):
        cache = casadm.load_cache(cache_dev)
        if cache.get_status() is not CacheStatus.incomplete:
            TestRun.fail(
                f"Cache {cache.cache_id} should be incomplete but is "
                f"{cache.get_status()}."
            )
        for core in cache.get_core_devices():
            if core.get_status() is not CoreStatus.active:
                TestRun.fail(f"Core {core.core_id} should be Active but is {core.get_status()}.")
        if hidden_core.get_status() is not CoreStatus.inactive:
            TestRun.fail(f"Hidden core should be Inactive but is {hidden_core.get_status()}.")
