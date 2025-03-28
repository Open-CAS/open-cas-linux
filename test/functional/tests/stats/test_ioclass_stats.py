#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import random
import pytest

from api.cas import casadm, ioclass_config
from api.cas.cache_config import (
    CleaningPolicy,
    CacheMode,
    CacheLineSize,
    CacheModeTrait,
    SeqCutOffPolicy,
)
from api.cas.cli_messages import (
    check_stderr_msg,
    get_stats_ioclass_id_not_configured,
    get_stats_ioclass_id_out_of_range,
)
from api.cas.statistics import (
    UsageStats,
    RequestStatsChunk,
    BlockStats,
    RequestStats,
    IoClassUsageStats,
    IoClassConfigStats,
)

from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_tools import create_directory, Filesystem
from test_utils.filesystem.file import File
from test_tools.os_tools import sync
from test_tools.udev import Udev
from connection.utils.output import CmdException
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "cache_mode",
    CacheMode.with_traits(CacheModeTrait.InsertWrite | CacheModeTrait.InsertRead),
)
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_basic(cache_mode: CacheMode, random_cls: CacheLineSize):
    """
    title: Basic test for retrieving IO class statistics.
    description: |
        Check if statistics are retrieved only for configured IO classes.
    pass_criteria:
      - Statistics are retrieved for configured IO classes.
      - Error is displayed when retrieving statistics for non-configured IO class.
      - Error is displayed when retrieving statistics for out of range IO class id.
    """
    min_ioclass_id = 11
    max_ioclass_id = 21
    mountpoint = posixpath.join(TestRun.TEST_RUN_DATA_PATH, "cas1-1")
    file_size_base = Unit.Blocks4096.value

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(Filesystem.ext4)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_dev=cache_device,
            cache_mode=cache_mode,
            cache_line_size=random_cls,
            force=True,
        )
        cache_id = cache.cache_id

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Add core to cache"):
        core = cache.add_core(core_dev=core_device)

    with TestRun.step("Reset core counters"):
        core.reset_counters()

    with TestRun.step("Create mountpoint directory"):
        create_directory(path=mountpoint)

    with TestRun.step("Prepare IO class config file and save it"):
        ioclass_list = [
            ioclass_config.IoClass(
                class_id=class_id,
                rule=f"file_size:le:{4096 * class_id}&done",
                priority=22,
            )
            for class_id in range(min_ioclass_id, max_ioclass_id)
        ]
        ioclass_config.IoClass.save_list_to_config_file(ioclass_list, True)

    with TestRun.step("Load IO class config file"):
        cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Generate files with particular sizes in temporary folder"):
        file_list = []
        for class_id in range(min_ioclass_id, max_ioclass_id):
            path = posixpath.join(
                TestRun.TEST_RUN_DATA_PATH, f"test_file_{file_size_base * class_id}"
            )
            File.create_file(path)
            file = File(path)
            file.padding(Size(file_size_base * class_id, Unit.Byte))
            file_list.append(file)

    with TestRun.step("Mount exported object"):
        core.mount(mountpoint)

    with TestRun.step("Prepare IO class config file and save it"):
        ioclass_list = [
            ioclass_config.IoClass(
                class_id=class_id,
                rule=f"file_size:le:{4096 * class_id}&done",
                priority=22,
            )
            for class_id in range(min_ioclass_id, max_ioclass_id)
        ]
        ioclass_config.IoClass.save_list_to_config_file(ioclass_list, True)

    with TestRun.step("Load IO class config file"):
        casadm.load_io_classes(cache_id, file=ioclass_config.default_config_file_path)

    with TestRun.step(
        "Try retrieving IO class stats for allowed id values and one out of range id"
    ):
        for class_id in range(ioclass_config.MAX_IO_CLASS_ID + 2):
            out_of_range = " out of range" if class_id > ioclass_config.MAX_IO_CLASS_ID else ""

            with TestRun.group(f"Checking{out_of_range} IO class id {class_id}..."):
                expected = class_id == 0 or class_id in range(min_ioclass_id, max_ioclass_id)

                try:
                    casadm.print_statistics(cache_id=cache_id, io_class_id=class_id, io_class=True)
                    if not expected:
                        TestRun.LOGGER.error(
                            f"Stats retrieved for not configured IO class {class_id}"
                        )
                except CmdException as e:
                    if expected:
                        TestRun.LOGGER.error(f"Stats not retrieved for IO class id: {class_id}")
                    elif class_id <= ioclass_config.MAX_IO_CLASS_ID:
                        if not check_stderr_msg(e.output, get_stats_ioclass_id_not_configured):
                            TestRun.LOGGER.error(
                                f"Wrong message for unused IO class id: {class_id}"
                            )
                    elif not check_stderr_msg(e.output, get_stats_ioclass_id_out_of_range):
                        TestRun.LOGGER.error(
                            f"Wrong message for out of range IO class id: {class_id}"
                        )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "cache_mode",
    CacheMode.with_traits(CacheModeTrait.InsertWrite | CacheModeTrait.InsertRead),
)
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_sum(cache_mode: CacheMode, random_cls: CacheLineSize):
    """
    title: Test for sum of IO class statistics.
    description: |
      Check if statistics for configured IO classes sum up to cache/core statistics.
    pass_criteria:
      - Per class cache IO class statistics sum up to cache statistics.
      - Per class core IO class statistics sum up to core statistics.
    """
    min_ioclass_id = 11
    max_ioclass_id = 22
    mountpoint = posixpath.join(TestRun.TEST_RUN_DATA_PATH, "cas1-1")
    file_size_base = Unit.Blocks4096.value

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(Filesystem.ext4)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_dev=cache_device,
            cache_mode=cache_mode,
            cache_line_size=random_cls,
            force=True,
        )

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Add core to cache"):
        core = cache.add_core(core_dev=core_device)

    with TestRun.step("Reset counter for each core"):
        core.reset_counters()

    with TestRun.step("Create mountpoint directory"):
        create_directory(path=mountpoint)

    with TestRun.step("Prepare IO class config file and save it"):
        ioclass_list = [
            ioclass_config.IoClass(
                class_id=class_id,
                rule=f"file_size:le:{file_size_base * class_id}&done",
                priority=22,
            )
            for class_id in range(min_ioclass_id, max_ioclass_id)
        ]
        ioclass_config.IoClass.save_list_to_config_file(ioclass_list, True)

    with TestRun.step("Load IO class config file"):
        cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Generate files with particular sizes in temporary folder"):
        file_list = []
        for class_id in range(min_ioclass_id, max_ioclass_id):
            path = posixpath.join(
                TestRun.TEST_RUN_DATA_PATH, f"test_file_{file_size_base * class_id}"
            )
            File.create_file(path)
            file = File(path)
            file.padding(Size(file_size_base * class_id, Unit.Byte))
            file_list.append(file)

    with TestRun.step("Mount exported object"):
        core.mount(mountpoint)

    with TestRun.step("Copy files to mounted exported object"):
        for file in file_list:
            file.copy(mountpoint)
            sync()

        # To prevent stats pollution by filesystem requests, umount exported object
        # after files are copied
        core.unmount()
        sync()

    with TestRun.step("Check if per class cache IO class statistics sum up to cache statistics"):
        ioclass_id_list = list(range(min_ioclass_id, max_ioclass_id))
        # Append default IO class id
        ioclass_id_list.append(0)

        cache_stats = cache.get_statistics(
            stat_filter=[casadm.StatsFilter.usage, casadm.StatsFilter.req, casadm.StatsFilter.blk]
        )
        ioclass_stats_list = [
            cache.get_io_class_statistics(
                io_class_id=ioclass_id,
                stat_filter=[
                    casadm.StatsFilter.usage,
                    casadm.StatsFilter.req,
                    casadm.StatsFilter.blk,
                ],
            )
            for ioclass_id in ioclass_id_list
        ]

        for ioclass_stats in ioclass_stats_list:
            for cache_stat, io_class_stat in zip(cache_stats, ioclass_stats):
                # Name of stats, which should not be compared
                # UsageStats: clean, occupancy, free
                if isinstance(cache_stat, UsageStats):
                    cache_stat.dirty -= io_class_stat.dirty

                elif isinstance(cache_stat, RequestStats):
                    cache_stat.pass_through_reads -= io_class_stat.pass_through_reads
                    cache_stat.pass_through_writes -= io_class_stat.pass_through_writes
                    cache_stat.requests_serviced -= io_class_stat.requests_serviced
                    cache_stat.requests_total -= io_class_stat.requests_total
                    for cache_stat_d, io_class_stat_d in zip(
                        [cache_stat.read, cache_stat.write],
                        [io_class_stat.read, io_class_stat.write],
                    ):
                        cache_stat_d.full_misses -= io_class_stat_d.full_misses
                        cache_stat_d.hits -= io_class_stat_d.hits
                        cache_stat_d.part_misses -= io_class_stat_d.part_misses
                        cache_stat_d.total -= io_class_stat_d.total

                elif isinstance(cache_stat, BlockStats):
                    for cache_stat_d, io_class_stat_d in zip(
                        [
                            cache_stat.cache,
                            cache_stat.core,
                            cache_stat.exp_obj,
                        ],
                        [
                            io_class_stat.cache,
                            io_class_stat.core,
                            io_class_stat.exp_obj,
                        ],
                    ):
                        cache_stat_d.reads -= io_class_stat_d.reads
                        cache_stat_d.writes -= io_class_stat_d.writes
                        cache_stat_d.total -= io_class_stat_d.total

        stat_val = []
        for cache_stat in cache_stats:
            if isinstance(cache_stat, UsageStats):
                stat_val.append(cache_stat.dirty.get_value())
                stat_name = cache_stat
            else:
                for stat_name in cache_stat:
                    if isinstance(stat_name, Size):
                        stat_val.append(stat_name.get_value())
                    elif isinstance(stat_name, RequestStatsChunk):
                        stat_val.append([stat for stat in stat_name])
                    else:
                        stat_val.append(stat_name)

            if all(stat_val) != 0:
                TestRun.LOGGER.error(f"Diverged for cache!\n {stat_name}")

    with TestRun.step("Check if per class core IO class statistics sum up to core statistics"):
        core_stats = core.get_statistics(
            stat_filter=[casadm.StatsFilter.usage, casadm.StatsFilter.req, casadm.StatsFilter.blk]
        )
        ioclass_stats_list = [
            core.get_io_class_statistics(
                io_class_id=ioclass_id,
                stat_filter=[
                    casadm.StatsFilter.usage,
                    casadm.StatsFilter.req,
                    casadm.StatsFilter.blk,
                ],
            )
            for ioclass_id in ioclass_id_list
        ]

        for ioclass_stats in ioclass_stats_list:
            for core_stat, io_class_stat in zip(core_stats, ioclass_stats):
                # Name of stats, which should not be compared
                # UsageStats: clean, occupancy, free
                if isinstance(core_stat, UsageStats):
                    core_stat.dirty -= io_class_stat.dirty

                elif isinstance(core_stat, RequestStats):
                    core_stat.pass_through_reads -= io_class_stat.pass_through_reads
                    core_stat.pass_through_writes -= io_class_stat.pass_through_writes
                    core_stat.requests_serviced -= io_class_stat.requests_serviced
                    core_stat.requests_total -= io_class_stat.requests_total
                    for cache_stat_d, io_class_stat_d in zip(
                        [core_stat.read, core_stat.write],
                        [io_class_stat.read, io_class_stat.write],
                    ):
                        cache_stat_d.full_misses -= io_class_stat_d.full_misses
                        cache_stat_d.hits -= io_class_stat_d.hits
                        cache_stat_d.part_misses -= io_class_stat_d.part_misses
                        cache_stat_d.total -= io_class_stat_d.total

                elif isinstance(cache_stat, BlockStats):
                    for core_stat_d, io_class_stat_d in zip(
                        [
                            core_stat.cache,
                            core_stat.core,
                            core_stat.exp_obj,
                        ],
                        [
                            io_class_stat.cache,
                            io_class_stat.core,
                            io_class_stat.exp_obj,
                        ],
                    ):
                        core_stat_d.reads -= io_class_stat_d.reads
                        core_stat_d.writes -= io_class_stat_d.writes
                        core_stat_d.total -= io_class_stat_d.total

        stat_val = []
        for core_stat in core_stats:
            if isinstance(core_stat, UsageStats):
                stat_val.append(core_stat.dirty.get_value())
                stat_name = core_stat
            else:
                for stat_name in core_stat:
                    if isinstance(stat_name, Size):
                        stat_val.append(stat_name.get_value())
                    elif isinstance(stat_name, RequestStatsChunk):
                        stat_val.append([stat for stat in stat_name])
                    else:
                        stat_val.append(stat_name)

            if all(stat_val) != 0:
                TestRun.LOGGER.error(f"Diverged for core!\n {stat_name}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_sections(random_cls):
    """
    title: Test for cache/core IO class statistics sections.
    description: |
        Check if IO class statistics sections for cache/core print all required entries and
        no additional ones.
    pass_criteria:
      - Section statistics contain all required entries.
    """
    cache_modes = CacheMode.with_traits(CacheModeTrait.InsertWrite | CacheModeTrait.InsertRead)
    cache_count = len(cache_modes)
    cores_per_cache = 3
    ioclass_stat_filter = [
        casadm.StatsFilter.req,
        casadm.StatsFilter.usage,
        casadm.StatsFilter.conf,
        casadm.StatsFilter.blk,
    ]
    mountpoint = posixpath.join(TestRun.TEST_RUN_DATA_PATH, "cas1-1")

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(500, Unit.MebiByte)] * cache_count)
        core_device.create_partitions([Size(2, Unit.GibiByte)] * cache_count * cores_per_cache)

        cache_devices = cache_device.partitions
        core_devices = core_device.partitions

    with TestRun.step("Create filesystem on each core device"):
        for core_device in core_devices:
            core_device.create_filesystem(Filesystem.ext4)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache for each cache device"):
        cache_list = [
            casadm.start_cache(
                cache_dev=device,
                cache_mode=cache_mode,
                cache_line_size=random_cls,
                force=True,
            )
            for device, cache_mode in zip(cache_devices, cache_modes)
        ]

    with TestRun.step("Disable cleaning and sequential cutoff"):
        for cache in cache_list:
            cache.set_cleaning_policy(CleaningPolicy.nop)
            cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step(f"Add {cores_per_cache} cores to each cache"):
        core_list = [cache.add_core(core_dev=core_dev) for core_dev in core_devices]

    with TestRun.step("Reset counter for each core"):
        for core in core_list:
            core.reset_counters()

    with TestRun.step("Create mountpoint directory"):
        create_directory(path=mountpoint)

    with TestRun.step("Validate displayed statistics for default IO class on each cache"):
        for cache in cache_list:
            statistics = cache.get_io_class_statistics(
                io_class_id=0, stat_filter=ioclass_stat_filter
            )
            for stat_name in ioclass_stat_filter:
                io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                if not any(isinstance(statistic, io_class_stat_name) for statistic in statistics):
                    TestRun.LOGGER.error(f"Value for {stat_name} not displayed in output")

            if not len(ioclass_stat_filter) != len([statistics]):
                parsed_filter = ", ".join([(str(stat) + "_stats") for stat in ioclass_stat_filter])
                parsed_stats = ", ".join(vars(statistics))
                TestRun.LOGGER.error(
                    "Wrong number of statistics in output\n"
                    f"Expected:{parsed_filter}\n"
                    f"Got: {parsed_stats}"
                )

    with TestRun.step("Validate displayed statistics for default IO class on each core"):
        for cache in cache_list:
            cache_core_device_list = [core for core in core_list if core.cache_id == cache.cache_id]
            for core in cache_core_device_list:
                statistics = core.get_io_class_statistics(
                    io_class_id=0, stat_filter=ioclass_stat_filter
                )

                for stat_name in ioclass_stat_filter:
                    io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                    if not any(
                        isinstance(statistic, io_class_stat_name) for statistic in statistics
                    ):
                        TestRun.LOGGER.error(f"Value for {stat_name} not displayed in output")

                if not len(ioclass_stat_filter) != len([statistics]):
                    parsed_filter = ", ".join(
                        [(str(stat) + "_stats") for stat in ioclass_stat_filter]
                    )
                    parsed_stats = ", ".join(vars(statistics))
                    TestRun.LOGGER.error(
                        "Wrong number of statistics in output\n"
                        f"Expected:{parsed_filter}\n"
                        f"Got: {parsed_stats}"
                    )

    with TestRun.step("Load random IO class configuration for each cache"):
        for cache in cache_list:
            random_list = ioclass_config.IoClass.generate_random_ioclass_list(
                ioclass_config.MAX_IO_CLASS_ID + 1
            )
            ioclass_config.IoClass.save_list_to_config_file(random_list, add_default_rule=False)
            cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Validate displayed statistics for configured IO class on each cache"):
        for cache in cache_list:
            statistics = cache.get_io_class_statistics(
                io_class_id=0, stat_filter=ioclass_stat_filter
            )
            for stat_name in ioclass_stat_filter:
                io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                if not any(isinstance(statistic, io_class_stat_name) for statistic in statistics):
                    TestRun.LOGGER.error(f"Value for {stat_name} not displayed in output")

            statistics = cache.get_io_class_statistics(
                io_class_id=0, stat_filter=ioclass_stat_filter, percentage_val=True
            )
            for stat_name in ioclass_stat_filter:
                io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                if not any(isinstance(statistic, io_class_stat_name) for statistic in statistics):
                    TestRun.LOGGER.error(f"Percentage for {stat_name} not displayed in output")

            if not len(ioclass_stat_filter) != len([statistics]):
                parsed_filter = ", ".join([(str(stat) + "_stats") for stat in ioclass_stat_filter])
                parsed_stats = ", ".join(vars(statistics))
                TestRun.LOGGER.error(
                    "Wrong number of statistics in output\n"
                    f"Expected:{parsed_filter}\n"
                    f"Got: {parsed_stats}"
                )

    with TestRun.step("Validate displayed statistics for configured IO class on each core"):
        for cache in cache_list:
            cache_core_device_list = [core for core in core_list if core.cache_id == cache.cache_id]
            for core in cache_core_device_list:
                core_info = f"Core {core.cache_id}-{core.core_id}"
                for class_id in range(ioclass_config.MAX_IO_CLASS_ID + 1):
                    statistics = cache.get_io_class_statistics(
                        io_class_id=class_id, stat_filter=ioclass_stat_filter
                    )
                    for stat_name in ioclass_stat_filter:
                        io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                        if not any(
                            isinstance(statistic, io_class_stat_name) for statistic in statistics
                        ):
                            TestRun.LOGGER.error(
                                f"Value for {core_info} - {stat_name} not displayed in output"
                            )

                    if not len(ioclass_stat_filter) != len([statistics]):
                        parsed_filter = ", ".join(
                            [(str(stat) + "_stats") for stat in ioclass_stat_filter]
                        )
                        parsed_stats = ", ".join(vars(statistics))
                        TestRun.LOGGER.error(
                            "Wrong number of statistics in output\n"
                            f"Expected:{parsed_filter}\n"
                            f"Got: {parsed_stats}"
                        )

                    statistics = cache.get_io_class_statistics(
                        io_class_id=class_id,
                        stat_filter=ioclass_stat_filter,
                        percentage_val=True,
                    )
                    for stat_name in ioclass_stat_filter:
                        io_class_stat_name = get_checked_ioclass_statistics(stat_name)
                        if not any(
                            isinstance(statistic, io_class_stat_name) for statistic in statistics
                        ):
                            TestRun.LOGGER.error(
                                f"Percentage for {core_info} - {stat_name} not displayed in output"
                            )

                    if not len(ioclass_stat_filter) != len([statistics]):
                        parsed_filter = ", ".join(
                            [(str(stat) + "_stats") for stat in ioclass_stat_filter]
                        )
                        parsed_stats = ", ".join(vars(statistics))
                        TestRun.LOGGER.error(
                            "Wrong number of statistics in output\n"
                            f"Expected:{parsed_filter}\n"
                            f"Got: {parsed_stats}"
                        )


def get_checked_ioclass_statistics(stat_filter: casadm.StatsFilter):
    match stat_filter:
        case casadm.StatsFilter.conf:
            return IoClassConfigStats
        case casadm.StatsFilter.usage:
            return IoClassUsageStats
        case casadm.StatsFilter.req:
            return RequestStats
        case casadm.StatsFilter.blk:
            return BlockStats
