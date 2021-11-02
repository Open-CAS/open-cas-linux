#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import random

import pytest

from api.cas import casadm
from api.cas import ioclass_config
from api.cas.cache_config import CleaningPolicy, CacheMode, CacheLineSize
from api.cas.casadm import StatsFilter
from api.cas.cli_messages import (
    check_stderr_msg,
    get_stats_ioclass_id_not_configured,
    get_stats_ioclass_id_out_of_range
)
from api.cas.statistics import (
    config_stats_ioclass,
    usage_stats,
    usage_stats_ioclass,
    request_stats,
    block_stats_core,
    block_stats_cache
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.os_utils import sync, Udev
from test_utils.output import CmdException
from test_utils.size import Size, Unit

IoClass = ioclass_config.IoClass

mountpoint = "/tmp/cas1-1"
cache_id = 1


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_basic(random_cls):
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

    with TestRun.step("Test prepare"):
        prepare(random_cls)

    with TestRun.step("Prepare IO class config file"):
        ioclass_list = []
        for class_id in range(min_ioclass_id, max_ioclass_id):
            ioclass_list.append(IoClass(
                class_id=class_id,
                rule=f"file_size:le:{4096 * class_id}&done",
                priority=22
            ))
        IoClass.save_list_to_config_file(ioclass_list, True)

    with TestRun.step("Load IO class config file"):
        casadm.load_io_classes(cache_id, file=ioclass_config.default_config_file_path)

    with TestRun.step("Try retrieving IO class stats for all allowed id values "
                      "and one out of range id"):
        for class_id in range(ioclass_config.MAX_IO_CLASS_ID + 2):
            out_of_range = " out of range" if class_id > ioclass_config.MAX_IO_CLASS_ID else ""
            with TestRun.group(f"Checking{out_of_range} IO class id {class_id}..."):
                expected = class_id == 0 or class_id in range(min_ioclass_id, max_ioclass_id)
                try:
                    casadm.print_statistics(
                        cache_id=cache_id,
                        io_class_id=class_id,
                        per_io_class=True)
                    if not expected:
                        TestRun.LOGGER.error(
                            f"Stats retrieved for not configured IO class {class_id}")
                except CmdException as e:
                    if expected:
                        TestRun.LOGGER.error(f"Stats not retrieved for IO class id: {class_id}")
                    elif class_id <= ioclass_config.MAX_IO_CLASS_ID:
                        if not check_stderr_msg(e.output, get_stats_ioclass_id_not_configured):
                            TestRun.LOGGER.error(
                                f"Wrong message for unused IO class id: {class_id}")
                    elif not check_stderr_msg(e.output, get_stats_ioclass_id_out_of_range):
                        TestRun.LOGGER.error(
                            f"Wrong message for out of range IO class id: {class_id}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_sum(random_cls):
    """
        title: Test for sum of IO class statistics.
        description: |
          Check if statistics for configured IO classes sum up to cache/core statistics.
        pass_criteria:
          - Per class cache IO class statistics sum up to cache statistics.
          - Per class core IO class statistics sum up to core statistics.
    """

    min_ioclass_id = 1
    max_ioclass_id = 11
    file_size_base = Unit.Blocks4096.value

    with TestRun.step("Test prepare"):
        caches, cores = prepare(random_cls)
        cache, core = caches[0], cores[0]

    with TestRun.step("Prepare IO class config file"):
        ioclass_list = []
        for class_id in range(min_ioclass_id, max_ioclass_id):
            ioclass_list.append(IoClass(
                class_id=class_id,
                rule=f"file_size:le:{file_size_base * class_id}&done",
                priority=22
            ))
        IoClass.save_list_to_config_file(ioclass_list, True)

    with TestRun.step("Load IO class config file"):
        cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Generate files with particular sizes in temporary folder"):
        files_list = []
        for class_id in range(min_ioclass_id, max_ioclass_id):
            path = f"/tmp/test_file_{file_size_base * class_id}"
            File.create_file(path)
            f = File(path)
            f.padding(Size(file_size_base * class_id, Unit.Byte))
            files_list.append(f)

    with TestRun.step("Copy files to mounted core"):
        core.mount(mountpoint)
        for f in files_list:
            TestRun.LOGGER.info(f"Copying file {f.name} to mounted core")
            f.copy(mountpoint)
            sync()
        # To prevent stats pollution by filesystem requests, umount core device
        # after files are copied
        core.unmount()
        sync()

    with TestRun.step("Check if per class cache IO class statistics sum up to cache statistics"):
        # Name of stats, which should not be compared
        not_compare_stats = ["clean", "occupancy", "free"]
        ioclass_id_list = list(range(min_ioclass_id, max_ioclass_id))
        # Append default IO class id
        ioclass_id_list.append(0)

        cache_stats = cache.get_statistics_flat(
            stat_filter=[StatsFilter.usage, StatsFilter.req, StatsFilter.blk]
        )
        for ioclass_id in ioclass_id_list:
            ioclass_stats = cache.get_statistics_flat(
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
            if stat_val != 0:
                TestRun.LOGGER.error(f"{stat_name} diverged for cache!\n")

    with TestRun.step("Check if per class core IO class statistics sum up to core statistics"):
        core_stats = core.get_statistics_flat(
            stat_filter=[StatsFilter.usage, StatsFilter.req, StatsFilter.blk]
        )
        for ioclass_id in ioclass_id_list:
            ioclass_stats = core.get_statistics_flat(
                stat_filter=[StatsFilter.usage, StatsFilter.req, StatsFilter.blk],
                io_class_id=ioclass_id,
            )
            for stat_name in core_stats:
                if stat_name in not_compare_stats:
                    continue
                core_stats[stat_name] -= ioclass_stats[stat_name]

        for stat_name in core_stats:
            if stat_name in not_compare_stats:
                continue
            stat_val = (
                core_stats[stat_name].get_value()
                if isinstance(core_stats[stat_name], Size)
                else core_stats[stat_name]
            )
            if stat_val != 0:
                TestRun.LOGGER.error(f"{stat_name} diverged for core!\n")

        with TestRun.step("Test cleanup"):
            for f in files_list:
                f.remove()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("stat_filter", [StatsFilter.req, StatsFilter.usage, StatsFilter.conf,
                                         StatsFilter.blk])
@pytest.mark.parametrize("per_core", [True, False])
@pytest.mark.parametrize("random_cls", [random.choice(list(CacheLineSize))])
def test_ioclass_stats_sections(stat_filter, per_core, random_cls):
    """
        title: Test for cache/core IO class statistics sections.
        description: |
            Check if IO class statistics sections for cache/core print all required entries and
            no additional ones.
        pass_criteria:
          - Section statistics contain all required entries.
          - Section statistics do not contain any additional entries.
    """
    with TestRun.step("Test prepare"):
        caches, cores = prepare(random_cls, cache_count=4, cores_per_cache=3)

    with TestRun.step(f"Validate displayed {stat_filter.name} statistics for default IO class for "
                      f"{'cores' if per_core else 'caches'}"):
        for cache in caches:
            with TestRun.group(f"Cache {cache.cache_id}"):
                for core in cache.get_core_devices():
                    if per_core:
                        TestRun.LOGGER.info(f"Core {core.cache_id}-{core.core_id}")
                    statistics = (
                        core.get_statistics_flat(
                            io_class_id=0, stat_filter=[stat_filter]) if per_core
                        else cache.get_statistics_flat(
                            io_class_id=0, stat_filter=[stat_filter]))
                    validate_statistics(statistics, stat_filter, per_core)
                    if not per_core:
                        break

    with TestRun.step("Load random IO class configuration for each cache"):
        for cache in caches:
            random_list = IoClass.generate_random_ioclass_list(ioclass_config.MAX_IO_CLASS_ID + 1)
            IoClass.save_list_to_config_file(random_list, add_default_rule=False)
            cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step(f"Validate displayed {stat_filter.name} statistics for every configured IO "
                      f"class for all {'cores' if per_core else 'caches'}"):
        for cache in caches:
            with TestRun.group(f"Cache {cache.cache_id}"):
                for core in cache.get_core_devices():
                    core_info = f"Core {core.cache_id}-{core.core_id} ," if per_core else ""
                    for class_id in range(ioclass_config.MAX_IO_CLASS_ID + 1):
                        with TestRun.group(core_info + f"IO class id {class_id}"):
                            statistics = (
                                core.get_statistics_flat(class_id, [stat_filter]) if per_core
                                else cache.get_statistics_flat(class_id, [stat_filter]))
                            validate_statistics(statistics, stat_filter, per_core)
                            if stat_filter == StatsFilter.conf:  # no percentage statistics for conf
                                continue
                            statistics_percents = (
                                core.get_statistics_flat(
                                    class_id, [stat_filter], percentage_val=True) if per_core
                                else cache.get_statistics_flat(
                                    class_id, [stat_filter], percentage_val=True))
                            validate_statistics(statistics_percents, stat_filter, per_core)
                    if not per_core:
                        break


def get_checked_statistics(stat_filter: StatsFilter, per_core: bool):
    if stat_filter == StatsFilter.conf:
        return config_stats_ioclass
    if stat_filter == StatsFilter.usage:
        return usage_stats_ioclass
    if stat_filter == StatsFilter.blk:
        return block_stats_core if per_core else block_stats_cache
    if stat_filter == StatsFilter.req:
        return request_stats


def validate_statistics(statistics: dict, stat_filter: StatsFilter, per_core: bool):
    for stat_name in get_checked_statistics(stat_filter, per_core):
        if stat_name not in statistics.keys():
            TestRun.LOGGER.error(f"Value for {stat_name} not displayed in output")
        else:
            del statistics[stat_name]
    if len(statistics.keys()):
        TestRun.LOGGER.error(f"Additional statistics found: {', '.join(statistics.keys())}")


def prepare(random_cls, cache_count=1, cores_per_cache=1):
    cache_modes = [CacheMode.WT, CacheMode.WB, CacheMode.WA, CacheMode.WO]
    ioclass_config.remove_ioclass_config()

    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']

    cache_device.create_partitions([Size(500, Unit.MebiByte)] * cache_count)
    core_device.create_partitions([Size(2, Unit.GibiByte)] * cache_count * cores_per_cache)

    cache_devices = cache_device.partitions
    core_devices = core_device.partitions
    for core_device in core_devices:
        core_device.create_filesystem(Filesystem.ext4)

    Udev.disable()
    caches, cores = [], []
    for i, cache_device in enumerate(cache_devices):
        TestRun.LOGGER.info(f"Starting cache on {cache_device.path}")
        cache = casadm.start_cache(cache_device,
                                   force=True,
                                   cache_mode=cache_modes[i],
                                   cache_line_size=random_cls)
        caches.append(cache)
        TestRun.LOGGER.info("Setting cleaning policy to NOP")
        cache.set_cleaning_policy(CleaningPolicy.nop)
        for core_device in core_devices[i * cores_per_cache:(i + 1) * cores_per_cache]:
            TestRun.LOGGER.info(
                f"Adding core device {core_device.path} to cache {cache.cache_id}")
            core = cache.add_core(core_dev=core_device)
            core.reset_counters()
            cores.append(core)

    TestRun.executor.run_expect_success(f"mkdir -p {mountpoint}")

    return caches, cores
