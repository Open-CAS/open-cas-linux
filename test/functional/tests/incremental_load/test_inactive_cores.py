#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.casadm_parser import get_cas_devices_dict, get_inactive_cores
from api.cas.core import Core, CoreStatus
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_inactive_stats_conf():
    """
    title: Test for inactive core configuration statistics.
    description: |
        Test the cache inactive core configuration statistics after removing one of core devices
        and loading cache.
    pass_criteria:
      - Cache can be loaded with inactive core device.
      - CAS correctly reports inactive core statistics in cache configuration statistics after
      loading cache.
    """
    core_number = 3

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * core_number)

        cache_device = cache_device.partitions[0]
        core_device_partitions = core_device.partitions

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_device, force=True)

    with TestRun.step("Add cores to the cache"):
        for core_device_part in core_device_partitions:
            cache.add_core(core_dev=core_device_part)

    with TestRun.step("Check if correct number of inactive cores is displayed in cache statistics"):
        stats = cache.get_statistics()
        if stats.config_stats.inactive_core_devices != 0:
            TestRun.fail("Inactive core in statistics after starting cache")

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Remove last core device"):
        core_device.remove_partition(part=core_device_partitions[-1])

    with TestRun.step("Load cache with missing core device"):
        cache = casadm.start_cache(cache_device, load=True)

    with TestRun.step(
        "Check if correct number of cores and inactive cores is displayed in cache statistics"
    ):
        stats = cache.get_statistics()
        if stats.config_stats.core_dev != core_number:
            TestRun.fail(
                "Wrong number of cores after loading the cache\n"
                f"Actual number of cores: {stats.config_stats.core_dev}\n"
                f"Expected number of cores: {core_number}"
            )
        if stats.config_stats.inactive_core_devices != 1:
            TestRun.fail(
                "Wrong number of inactive cores after loading the cache\n"
                f"Actual number of inactive cores: {stats.config_stats.inactive_core_devices}\n"
                "Expected number of inactive cores: 1"
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_inactive_stats_usage():
    """
    title: Test for inactive core usage statistics.
    description: |
        Test the cache inactive core usage statistics after removing one of core devices and loading
        cache.
    pass_criteria:
      - Cache can be loaded with inactive core device.
      - CAS correctly reports inactive core statistics in cache usage statistics after loading
      cache.
    """

    core_number = 3

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * core_number)

        cache_device = cache_device.partitions[0]
        core_device_partitions = core_device.partitions

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_device, force=True, cache_mode=CacheMode.WB)

    with TestRun.step("Add cores to the cache"):
        core_list = [
            cache.add_core(core_dev=core_device_part) for core_device_part in core_device_partitions
        ]

    with TestRun.step("Run I/O to each core"):
        for core in core_list:
            dd = (
                Dd()
                .input("/dev/zero")
                .output(core.path)
                .count(1000)
                .block_size(Size(4, Unit.KibiByte))
            )
            dd.run()

    with TestRun.step("Flush last core"):
        core_list[-1].flush_core()

    with TestRun.step("Stop cache with dirty data"):
        cache.stop(no_data_flush=True)

    with TestRun.step("Removing two of core devices"):
        core_device.remove_partition(part=core_device_partitions[0])
        core_device.remove_partition(part=core_device_partitions[1])

    with TestRun.step("Load cache with missing core devices"):
        cache = casadm.start_cache(cache_device, load=True)

    with TestRun.step("Check cores statistics"):
        active_cores_occupancy_stats = 0
        active_cores_clean_stats = 0
        active_cores_dirty_stats = 0

        active_cores = cache.get_core_devices()
        for core in active_cores:
            core_stats = core.get_statistics()
            active_cores_occupancy_stats += core_stats.usage_stats.occupancy
            active_cores_clean_stats += core_stats.usage_stats.clean
            active_cores_dirty_stats += core_stats.usage_stats.dirty

        inactive_cores_occupancy_stats = 0
        inactive_cores_clean_stats = 0
        inactive_cores_dirty_stats = 0

        inactive_cores = get_inactive_cores(cache_id=cache.cache_id)
        for core in inactive_cores:
            core_stats = core.get_statistics()
            inactive_cores_occupancy_stats += core_stats.usage_stats.occupancy
            inactive_cores_clean_stats += core_stats.usage_stats.clean
            inactive_cores_dirty_stats += core_stats.usage_stats.dirty

        cache_stats = cache.get_statistics()
        cache_usage_stats = cache_stats.usage_stats

        total_cores_occupancy_stats = active_cores_occupancy_stats + inactive_cores_occupancy_stats
        total_cores_dirty_stats = active_cores_dirty_stats + inactive_cores_dirty_stats
        total_cores_clean_stats = active_cores_clean_stats + inactive_cores_clean_stats

        if cache_usage_stats.occupancy != total_cores_occupancy_stats:
            TestRun.LOGGER.error(
                "Wrong number of occupancy blocks in cache usage stats\n"
                f"Actual number of occupancy blocks: {cache_usage_stats.occupancy}\n"
                f"Expected number of occupancy blocks: {total_cores_occupancy_stats}"
            )
        if cache_usage_stats.dirty != total_cores_dirty_stats:
            TestRun.LOGGER.error(
                "Wrong number of dirty blocks in cache usage stats\n"
                f"Actual number of dirty blocks: {cache_usage_stats.dirty}\n"
                f"Expected number of dirty blocks: {total_cores_dirty_stats}"
            )
        if cache_usage_stats.clean != total_cores_clean_stats:
            TestRun.LOGGER.error(
                "Wrong number of clean blocks in cache usage stats\n"
                f"Actual number of clean blocks: {cache_usage_stats.clean}\n"
                f"Expected number of clean blocks: {total_cores_clean_stats}"
            )
        if cache_usage_stats.inactive_occupancy != inactive_cores_occupancy_stats:
            TestRun.LOGGER.error(
                "Wrong number of occupancy blocks in inactive cache usage stats\n"
                f"Actual number of occupancy blocks: {cache_usage_stats.inactive_occupancy}\n"
                f"Expected number of occupancy blocks: {inactive_cores_occupancy_stats}"
            )
        if cache_usage_stats.inactive_dirty != inactive_cores_dirty_stats:
            TestRun.LOGGER.error(
                "Wrong number of dirty blocks in cache inactive usage stats\n"
                f"Actual number of dirty blocks: {cache_usage_stats.inactive_dirty}\n"
                f"Expected number of dirty blocks: {inactive_cores_dirty_stats}"
            )
        if cache_usage_stats.inactive_clean != inactive_cores_clean_stats:
            TestRun.LOGGER.error(
                "Wrong number of clean blocks in cache inactive usage stats\n"
                f"Actual number of clean blocks: {cache_usage_stats.inactive_clean}\n"
                f"Expected number of clean blocks: {inactive_cores_clean_stats}"
            )

        cache_usage_stats_percentage = cache.get_statistics(percentage_val=True).usage_stats

        # Calculate expected percentage value of inactive core stats
        inactive_occupancy_perc = round(
            100 * (cache_usage_stats.inactive_occupancy / cache_stats.config_stats.cache_size), 1
        )
        inactive_dirty_perc = round(
            100 * (cache_usage_stats.inactive_dirty / cache_stats.usage_stats.occupancy), 1
        )
        inactive_clean_perc = round(
            100 * (cache_usage_stats.inactive_clean / cache_stats.usage_stats.occupancy), 1
        )

        if cache_usage_stats_percentage.inactive_occupancy != inactive_occupancy_perc:
            TestRun.LOGGER.error(
                "Wrong occupancy blocks percentage in usage stats\n"
                f"Actual number of occupancy blocks percentage:"
                f" {cache_usage_stats_percentage.inactive_occupancy}\n"
                f"Expected number of occupancy blocks percentage: {inactive_occupancy_perc}"
            )
        if cache_usage_stats_percentage.inactive_dirty != inactive_dirty_perc:
            TestRun.LOGGER.error(
                "Wrong dirty blocks percentage in usage stats\n "
                "Actual number of dirty blocks percentage: "
                f"{cache_usage_stats_percentage.inactive_dirty}\n"
                f"Expected number of dirty blocks percentage: {inactive_dirty_perc}"
            )
        if cache_usage_stats_percentage.inactive_clean != inactive_clean_perc:
            TestRun.LOGGER.error(
                "Wrong clean blocks percentage in usage stats\n"
                "Actual number of clean blocks percentage: "
                f"{cache_usage_stats.inactive_clean}\n"
                f"Expected number of clean blocks percentage: {inactive_cores_clean_stats}"
            )
