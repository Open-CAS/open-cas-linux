#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_inactive():
    """
        1. Start cache with 3 cores.
        2. Stop cache.
        3. Remove one of core devices.
        4. Load cache.
        5. Check if cache has appropriate number of valid and inactive core devices.
    """
    cache, core_device = prepare()

    cache_device = cache.cache_device
    stats = cache.get_statistics()

    assert stats.config_stats.core_dev == 3
    assert stats.config_stats.inactive_core_dev == 0

    TestRun.LOGGER.info("Stopping cache")
    cache.stop()

    TestRun.LOGGER.info("Removing one of core devices")
    core_device.remove_partitions()
    core_device.create_partitions([Size(1, Unit.GibiByte), Size(1, Unit.GibiByte)])

    TestRun.LOGGER.info("Loading cache with missing core device")
    cache = casadm.start_cache(cache_device, load=True)
    stats = cache.get_statistics()

    assert stats.config_stats.core_dev == 3
    assert stats.config_stats.inactive_core_dev == 1


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_inactive_stats():
    """
        1. Start cache with 3 cores.
        2. Switch cache into WB mode.
        3. Issue IO to each core.
        4. Stop cache without flush.
        5. Remove two core devices.
        6. Load cache.
        7. Check if cache stats are equal to sum of valid and inactive cores stats.
        8. Check if percentage values are calculated properly.
    """
    cache, core_device = prepare()

    cache_device = cache.cache_device

    TestRun.LOGGER.info("Switching cache mode to WB")
    cache.set_cache_mode(cache_mode=CacheMode.WB)
    cores = cache.get_core_devices()
    TestRun.LOGGER.info("Issue IO to each core")
    for core in cores:
        dd = (
            Dd()
            .input("/dev/zero")
            .output(core.path)
            .count(1000)
            .block_size(Size(4, Unit.KibiByte))
        ).run()

    TestRun.LOGGER.info("Stopping cache with dirty data")
    cores[2].flush_core()
    cache.stop(no_data_flush=True)

    TestRun.LOGGER.info("Removing two of core devices")
    core_device.remove_partitions()
    core_device.create_partitions([Size(1, Unit.GibiByte)])

    TestRun.LOGGER.info("Loading cache with missing core device")
    cache = casadm.start_cache(cache_device, load=True)

    # Accumulate valid cores stats
    cores_occupancy = 0
    cores_clean = 0
    cores_dirty = 0
    cores = cache.get_core_devices()
    for core in cores:
        core_stats = core.get_statistics()
        cores_occupancy += core_stats.usage_stats.occupancy.value
        cores_clean += core_stats.usage_stats.clean.value
        cores_dirty += core_stats.usage_stats.dirty.value

    cache_stats = cache.get_statistics()
    # Add inactive core stats
    cores_occupancy += cache_stats.inactive_usage_stats.inactive_occupancy.value
    cores_clean += cache_stats.inactive_usage_stats.inactive_clean.value
    cores_dirty += cache_stats.inactive_usage_stats.inactive_dirty.value

    assert cache_stats.usage_stats.occupancy.value == cores_occupancy
    assert cache_stats.usage_stats.dirty.value == cores_dirty
    assert cache_stats.usage_stats.clean.value == cores_clean

    cache_stats_percentage = cache.get_statistics(percentage_val=True)
    # Calculate expected percentage value of inactive core stats
    inactive_occupancy_perc = (
        cache_stats.inactive_usage_stats.inactive_occupancy.value
        / cache_stats.config_stats.cache_size.value
    )
    inactive_clean_perc = (
        cache_stats.inactive_usage_stats.inactive_clean.value
        / cache_stats.usage_stats.occupancy.value
    )
    inactive_dirty_perc = (
        cache_stats.inactive_usage_stats.inactive_dirty.value
        / cache_stats.usage_stats.occupancy.value
    )

    inactive_occupancy_perc = round(100 * inactive_occupancy_perc, 1)
    inactive_clean_perc = round(100 * inactive_clean_perc, 1)
    inactive_dirty_perc = round(100 * inactive_dirty_perc, 1)

    TestRun.LOGGER.info(str(cache_stats_percentage))
    assert (
        inactive_occupancy_perc
        == cache_stats_percentage.inactive_usage_stats.inactive_occupancy
    )
    assert (
        inactive_clean_perc
        == cache_stats_percentage.inactive_usage_stats.inactive_clean
    )
    assert (
        inactive_dirty_perc
        == cache_stats_percentage.inactive_usage_stats.inactive_dirty
    )


def prepare():
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    cache_device.create_partitions([Size(500, Unit.MebiByte)])
    core_device.create_partitions(
        [Size(1, Unit.GibiByte), Size(1, Unit.GibiByte), Size(1, Unit.GibiByte)]
    )

    cache_device = cache_device.partitions[0]
    core_device_1 = core_device.partitions[0]
    core_device_2 = core_device.partitions[1]
    core_device_3 = core_device.partitions[2]

    TestRun.LOGGER.info("Staring cache")
    cache = casadm.start_cache(cache_device, force=True)
    TestRun.LOGGER.info("Adding core device")
    core_1 = cache.add_core(core_dev=core_device_1)
    core_2 = cache.add_core(core_dev=core_device_2)
    core_3 = cache.add_core(core_dev=core_device_3)

    return cache, core_device
