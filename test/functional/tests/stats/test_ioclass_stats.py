#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import pytest
from api.cas.casadm import StatsFilter
from api.cas import casadm
from api.cas import ioclass_config
from api.cas import casadm_parser
from api.cas.cache_config import CleaningPolicy
from tests.conftest import base_prepare
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit
from test_utils.os_utils import sync, Udev
from test_utils.filesystem.file import File

ioclass_config_path = "/tmp/opencas_ioclass.conf"
mountpoint = "/tmp/cas1-1"
cache_id = 1


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_stats_set():
    """Try to retrieve stats for all set ioclasses"""
    prepare()
    min_ioclass_id = 1
    max_ioclass_id = 11

    ioclass_config.create_ioclass_config(
        add_default_rule=True, ioclass_config_path=ioclass_config_path
    )

    TestRun.LOGGER.info("Preparing ioclass config file")
    for i in range(min_ioclass_id, max_ioclass_id):
        ioclass_config.add_ioclass(
            ioclass_id=(i + 10),
            eviction_priority=22,
            allocation=True,
            rule=f"file_size:le:{4096*i}&done",
            ioclass_config_path=ioclass_config_path,
        )
    casadm.load_io_classes(cache_id, file=ioclass_config_path)

    TestRun.LOGGER.info("Preparing ioclass config file")
    for i in range(32):
        if i != 0 or i not in range(min_ioclass_id, max_ioclass_id):
            with pytest.raises(Exception):
                assert casadm_parser.get_statistics(
                    cache_id=cache_id, io_class_id=True, filter=[StatsFilter.conf]
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_stats_sum():
    """Check if stats for all set ioclasses sum up to cache stats"""
    cache, core = prepare()
    min_ioclass_id = 1
    max_ioclass_id = 11
    file_size_base = Unit.KibiByte.value * 4

    TestRun.LOGGER.info("Preparing ioclass config file")
    ioclass_config.create_ioclass_config(
        add_default_rule=True, ioclass_config_path=ioclass_config_path
    )
    for i in range(min_ioclass_id, max_ioclass_id):
        ioclass_config.add_ioclass(
            ioclass_id=i,
            eviction_priority=22,
            allocation=True,
            rule=f"file_size:le:{file_size_base*i}&done",
            ioclass_config_path=ioclass_config_path,
        )
    cache.load_io_class(ioclass_config_path)

    TestRun.LOGGER.info("Generating files with particular sizes")
    files_list = []
    for i in range(min_ioclass_id, max_ioclass_id):
        path = f"/tmp/test_file_{file_size_base*i}"
        File.create_file(path)
        f = File(path)
        f.padding(Size(file_size_base * i, Unit.Byte))
        files_list.append(f)

    core.create_filesystem(Filesystem.ext4)

    cache.reset_counters()

    # Name of stats, which should not be compared
    not_compare_stats = ["clean", "occupancy"]
    ioclass_id_list = list(range(min_ioclass_id, max_ioclass_id))
    # Append default ioclass id
    ioclass_id_list.append(0)
    TestRun.LOGGER.info("Copying files to mounted core and stats check")
    for f in files_list:
        # To prevent stats pollution by filesystem requests, umount core device
        # after file is copied
        core.mount(mountpoint)
        f.copy(mountpoint)
        sync()
        core.unmount()
        sync()

        cache_stats = cache.get_cache_statistics(
            stat_filter=[StatsFilter.usage, StatsFilter.req, StatsFilter.blk]
        )
        for ioclass_id in ioclass_id_list:
            ioclass_stats = cache.get_cache_statistics(
                stat_filter=[StatsFilter.usage, StatsFilter.req, StatsFilter.blk],
                io_class_id=ioclass_id,
            )
            for stat_name in cache_stats:
                if stat_name in not_compare_stats:
                    continue
                cache_stats[stat_name] -= ioclass_stats[stat_name]

        for stat_name in cache_stats:
            if stat_name in not_compare_stats:
                continue
            stat_val = (
                cache_stats[stat_name].get_value()
                if isinstance(cache_stats[stat_name], Size)
                else cache_stats[stat_name]
            )
            assert stat_val == 0, f"{stat_name} diverged!\n"

    # Test cleanup
    for f in files_list:
        f.remove()


def flush_cache(cache_id):
    casadm.flush(cache_id=cache_id)
    sync()
    casadm.reset_counters(cache_id=cache_id)
    stats = casadm_parser.get_statistics(cache_id=cache_id, filter=[StatsFilter.blk])
    for key, value in stats.items():
        assert value.get_value(Unit.Blocks4096) == 0


def prepare():
    base_prepare()
    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']

    cache_device.create_partitions([Size(500, Unit.MebiByte)])
    core_device.create_partitions([Size(2, Unit.GibiByte)])

    cache_device = cache_device.partitions[0]
    core_device_1 = core_device.partitions[0]

    Udev.disable()

    TestRun.LOGGER.info(f"Staring cache")
    cache = casadm.start_cache(cache_device, force=True)
    TestRun.LOGGER.info(f"Setting cleaning policy to NOP")
    cache.set_cleaning_policy(CleaningPolicy.nop)
    TestRun.LOGGER.info(f"Adding core devices")
    core = cache.add_core(core_dev=core_device_1)

    output = TestRun.executor.run(f"mkdir -p {mountpoint}")
    if output.exit_code != 0:
        raise Exception(f"Failed to create mountpoint")

    return cache, core
