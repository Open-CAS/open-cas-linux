#
# Copyright(c) 2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.os_tools import sync, drop_caches
from test_tools.udev import Udev
from type_def.size import Unit, Size

dd_bs = Size(1, Unit.Blocks4096)
dd_count = 1230
cached_mountpoint = "/tmp/ioclass_core_id_test/cached"
not_cached_mountpoint = "/tmp/ioclass_core_id_test/not_cached"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_io_direction():
    """
    title: Test for `io_direction` classification rule
    description: |
        Test if IO direction rule correctly classifies IOs based on their direction. 
    pass_criteria:
     - Reads cached to IO class with 'io_direction:read' rule
     - Writes cached to IO class with 'io_direction:write' rule
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(5, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache, set NOP cleaning policy and disable sequential cutoff"):
        cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WT, force=True)
        casadm.set_param_cleaning(cache_id=cache.cache_id, policy=CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Add core"):
        cached_volume = casadm.add_core(cache, core_dev=core_device)

    with TestRun.step("Create new IO direction based classification rules"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(
            add_default_rule=False,
            ioclass_config_path=ioclass_config.default_config_file_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=1,
            eviction_priority=22,
            allocation="0.00",
            rule="metadata",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )

        read_ioclass_id = 11
        write_ioclass_id = 12

        ioclass_config.add_ioclass(
            ioclass_id=read_ioclass_id,
            eviction_priority=22,
            allocation="1.00",
            rule="io_direction:read&done",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=write_ioclass_id,
            eviction_priority=22,
            allocation="1.00",
            rule="io_direction:write&done",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )

    with TestRun.step("Load ioclass config file"):
        casadm.load_io_classes(
            cache_id=cache.cache_id, file=ioclass_config.default_config_file_path
        )

    with TestRun.step("Reset counters"):
        sync()
        drop_caches()
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Trigger IO read requests"):
        (Dd()
        .input(cached_volume.path)
        .output("/dev/null")
        .count(dd_count)
        .block_size(dd_bs)
        .iflag("direct")
        .run())

    with TestRun.step("Check IO class reads"):
        read_io_class_stat = cached_volume.get_io_class_statistics(io_class_id=read_ioclass_id).request_stats.read.total
        write_io_class_stat = cached_volume.get_io_class_statistics(io_class_id=write_ioclass_id).request_stats.read.total

        if read_io_class_stat != dd_count:
            TestRun.LOGGER.error(
                f"Wrong 'read' IO class stats! Expected {dd_count} total reads, actual: {read_io_class_stat}"
            )
        if write_io_class_stat != 0:
            TestRun.LOGGER.error(
                f"Wrong 'write' IO class stats! Expected 0 total reads, actual: {write_io_class_stat}"
            )

    with TestRun.step("Trigger IO write requests"):
        (Dd()
        .input("/dev/zero")
        .output(cached_volume.path)
        .count(dd_count)
        .block_size(dd_bs)
        .oflag("direct")
        .run())

    with TestRun.step("Check IO class writes"):
        read_io_class_stat = cached_volume.get_io_class_statistics(io_class_id=read_ioclass_id).request_stats.write.total
        write_io_class_stat = cached_volume.get_io_class_statistics(io_class_id=write_ioclass_id).request_stats.write.total

        if read_io_class_stat != 0:
            TestRun.LOGGER.error(
                f"Wrong 'read' IO class stats! Expected 0 total writes, actual: {read_io_class_stat}"
            )
        if write_io_class_stat != dd_count:
            TestRun.LOGGER.error(
                f"Wrong 'write' IO class stats! Expected {dd_count} total writes, actual: {write_io_class_stat}"
            )
