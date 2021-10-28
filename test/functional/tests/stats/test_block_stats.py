#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm
from api.cas import ioclass_config
from api.cas.cache_config import CacheMode, CleaningPolicy
from api.cas.casadm import StatsFilter
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit

ioclass_config_path = "/tmp/opencas_ioclass.conf"
mountpoint = "/tmp/cas1-1"
exported_obj_path_prefix = "/dev/cas1-"
cache_id = 1

# lists of cache and core block stats, that should have zero value for particular cache modes
write_wb_zero_stats = [
    "reads from core(s)",
    "writes to core(s)",
    "total to/from core(s)",
    "reads from cache",
    "reads from exported object(s)",
    "reads from core",
    "writes to core",
    "total to/from core",
    "reads from cache",
    "reads from exported object",
]
write_wt_zero_stats = [
    "reads from core(s)",
    "reads from cache",
    "reads from exported object(s)",
    "reads from core",
    "reads from exported object",
]
write_pt_zero_stats = [
    "reads from core(s)",
    "reads from cache",
    "writes to cache",
    "total to/from cache",
    "reads from exported object(s)",
    "reads from core",
    "reads from exported object",
]
write_wa_zero_stats = [
    "reads from core(s)",
    "reads from cache",
    "writes to cache",
    "total to/from cache",
    "reads from exported object(s)",
    "reads from core",
    "reads from exported object",
]
write_wo_zero_stats = [
    "reads from core(s)",
    "writes to core(s)",
    "total to/from core(s)",
    "reads from cache",
    "reads from exported object(s)",
    "reads from core",
    "writes to core",
    "total to/from core",
    "reads from exported object",
]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize(
    "cache_mode,zero_stats",
    [
        (CacheMode.WB, write_wb_zero_stats),
        (CacheMode.WT, write_wt_zero_stats),
        (CacheMode.PT, write_pt_zero_stats),
        (CacheMode.WA, write_wa_zero_stats),
        (CacheMode.WO, write_wo_zero_stats),
    ],
)
def test_block_stats_write(cache_mode, zero_stats):
    """Perform read and write operations to cache instance in different cache modes
        and check if block stats values are correct"""
    cache, cores = prepare(cache_mode)
    iterations = 10
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10

    flush(cache)

    # Check stats for cache after performing write operation
    for core in cores:
        dd_seek = 0
        dd = (
            Dd()
            .input("/dev/zero")
            .output(f"{core.path}")
            .count(dd_count)
            .block_size(dd_size)
            .oflag("direct")
        )
        # Since every IO has the same size, every stat should be increased with the same step.
        # So there is no need to keep value of every stat in separate variable
        cache_stat = (
            (dd_size.get_value(Unit.Blocks4096) * dd_count) * (core.core_id - 1) * iterations
        )
        for i in range(iterations):
            dd.seek(dd_seek)
            dd.run()
            cache_stats = cache.get_statistics_flat(stat_filter=[StatsFilter.blk])
            core_stats = core.get_statistics_flat(stat_filter=[StatsFilter.blk])

            # Check cache stats
            assumed_value = (dd_size.get_value(Unit.Blocks4096) * dd_count) * (i + 1)
            for key, value in cache_stats.items():
                if key in zero_stats:
                    assert value.get_value(Unit.Blocks4096) == 0, (
                        f"{key} has invalid value\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}, cache_stat {cache_stat}"
                    )
                else:
                    # For each next tested core, cache stats has to include
                    # sum of each previous core
                    assert cache_stat + assumed_value == value.get_value(Unit.Blocks4096), (
                        f"{key} has invalid value of {value.get_value(Unit.Blocks4096)}\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}, cache_stat {cache_stat}"
                    )

            # Check single core stats
            for key, value in core_stats.items():
                if key in zero_stats:
                    assert value.get_value(Unit.Blocks4096) == 0, (
                        f"{key} has invalid value of \n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}, cache_stat {cache_stat}"
                    )
                else:
                    assert assumed_value == value.get_value(Unit.Blocks4096), (
                        f"{key} has invalid value of {value.get_value(Unit.Blocks4096)}\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}, dd seek: {dd_seek}. Cache mode {cache_mode}"
                    )
        dd_seek += dd_count


# lists of cache and core block stats, that should have zero value for particular cache modes
read_wb_zero_stats = [
    "writes to core(s)",
    "reads from cache",
    "writes to exported object(s)",
    "writes to core",
    "writes to exported object",
]
read_wt_zero_stats = [
    "writes to core(s)",
    "reads from cache",
    "writes to exported object(s)",
    "writes to core",
    "writes to exported object",
]
read_pt_zero_stats = [
    "writes to core(s)",
    "reads from cache",
    "writes to cache",
    "total to/from cache",
    "writes to exported object(s)",
    "writes to core",
    "writes to exported object",
]
read_wa_zero_stats = [
    "writes to core(s)",
    "reads from cache",
    "writes to exported object(s)",
    "writes to core",
    "writes to exported object",
]
read_wo_zero_stats = [
    "writes to core(s)",
    "reads from cache",
    "writes to cache",
    "total to/from cache",
    "writes to exported object(s)",
    "writes to core",
    "writes to exported object",
]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize(
    "cache_mode,zero_stats",
    [
        (CacheMode.WB, read_wb_zero_stats),
        (CacheMode.WT, read_wt_zero_stats),
        (CacheMode.PT, read_pt_zero_stats),
        (CacheMode.WA, read_wa_zero_stats),
        (CacheMode.WO, read_wo_zero_stats),
    ],
)
def test_block_stats_read(cache_mode, zero_stats):
    """Perform read and write operations to cache instance in different cache modes
        and check if block stats values are correct"""
    cache, cores = prepare(cache_mode)
    iterations = 10
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10

    flush(cache)

    # Check stats for cache after performing read operation
    for core in cores:
        dd_skip = 0
        dd = (
            Dd()
            .output("/dev/zero")
            .input(f"{core.path}")
            .count(dd_count)
            .block_size(dd_size)
            .iflag("direct")
        )
        # Since every IO has the same size, every stat should be increased with the same step.
        # So there is no need to keep value of every stat in separate variable
        cache_stat = (
            (dd_size.get_value(Unit.Blocks4096) * dd_count) * (core.core_id - 1) * iterations
        )
        for i in range(iterations):
            dd.skip(dd_skip)
            dd.run()
            cache_stats = cache.get_statistics_flat(stat_filter=[StatsFilter.blk])
            core_stats = core.get_statistics_flat(stat_filter=[StatsFilter.blk])

            # Check cache stats
            assumed_value = (dd_size.get_value(Unit.Blocks4096) * dd_count) * (i + 1)
            for key, value in cache_stats.items():
                if key in zero_stats:
                    assert value.get_value(Unit.Blocks4096) == 0, (
                        f"{key} has invalid value\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}, cache_stat {cache_stat}"
                    )
                else:
                    # For each next tested core, cache stats has to include
                    # sum of each previous core
                    assert cache_stat + assumed_value == value.get_value(Unit.Blocks4096), (
                        f"{key} has invalid value of {value.get_value(Unit.Blocks4096)}\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}. Cache mode: {cache_mode}"
                    )

            # Check single core stats
            for key, value in core_stats.items():
                if key in zero_stats:
                    assert value.get_value(Unit.Blocks4096) == 0, (
                        f"{key} has invalid value\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count}. Cache mode: {cache_mode}"
                    )
                else:
                    assert assumed_value == value.get_value(Unit.Blocks4096), (
                        f"{key} has invalid value of {value.get_value(Unit.Blocks4096)}\n"
                        f"core id {core.core_id}, i: {i}, dd_size: "
                        f"{dd_size.get_value(Unit.Blocks4096)}\n"
                        f"dd count: {dd_count} dd skip {dd_skip}. Cache mode: {cache_mode}"
                    )

            dd_skip += dd_count


def flush(cache):
    cache.flush_cache()
    cache.reset_counters()
    stats = cache.get_statistics_flat(stat_filter=[StatsFilter.blk])
    for key, value in stats.items():
        assert value.get_value(Unit.Blocks4096) == 0


def prepare(cache_mode: CacheMode):
    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']

    cache_device.create_partitions([Size(500, Unit.MebiByte)])
    core_device.create_partitions(
        [Size(1, Unit.GibiByte), Size(1, Unit.GibiByte), Size(1, Unit.GibiByte)]
    )

    cache_device = cache_device.partitions[0]
    core_device_1 = core_device.partitions[0]
    core_device_2 = core_device.partitions[1]
    core_device_3 = core_device.partitions[2]

    Udev.disable()

    TestRun.LOGGER.info(f"Starting cache")
    cache = casadm.start_cache(cache_device, cache_mode=cache_mode, force=True)
    TestRun.LOGGER.info(f"Setting cleaning policy to NOP")
    casadm.set_param_cleaning(cache_id=cache_id, policy=CleaningPolicy.nop)
    TestRun.LOGGER.info(f"Adding core devices")
    core_1 = cache.add_core(core_dev=core_device_1)
    core_2 = cache.add_core(core_dev=core_device_2)
    core_3 = cache.add_core(core_dev=core_device_3)

    output = TestRun.executor.run(f"mkdir -p {mountpoint}")
    if output.exit_code != 0:
        raise Exception(f"Failed to create mountpoint")

    return cache, [core_1, core_2, core_3]
