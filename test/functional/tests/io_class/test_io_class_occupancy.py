#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from collections import namedtuple
from math import isclose

import pytest

from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.ioclass_config import IoClass, default_config_file_path
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.os_tools import sync
from test_tools.udev import Udev
from types.size import Unit, Size
from tests.io_class.io_class_common import (
    prepare,
    mountpoint,
    run_io_dir,
    get_io_class_occupancy,
    run_io_dir_read,
    get_io_class_usage,
)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("io_size_multiplication", [0.5, 2])
@pytest.mark.parametrize("cache_mode", [CacheMode.WT, CacheMode.WB])
def test_io_class_occupancy_directory_write(io_size_multiplication, cache_mode):
    """
    title: Test for max occupancy set for ioclass based on directory
    description: |
      Create ioclass for 3 different directories, each with different
      max cache occupancy configured. Run IO against each directory and see
      if occupancy limit is respected.
    pass_criteria:
      - Max occupancy is set correctly for each ioclass
      - Each ioclass does not exceed max occupancy
    """
    cache_line_size = CacheLineSize.LINE_64KiB

    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=cache_mode, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, 3, 0.10, f"{mountpoint}/A"),
            IoclassConfig(2, 4, 0.20, f"{mountpoint}/B"),
            IoclassConfig(3, 5, 0.30, f"{mountpoint}/C"),
        ]

        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old ioclass config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default io classes"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add io classes for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step("Reset cache stats"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Check initial occupancy"):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.LOGGER.error(
                    f"Incorrect inital occupancy for ioclass id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step(
        f"To each directory perform IO"
        f" with size of {io_size_multiplication} max io_class occupancy"
    ):
        for io_class in io_classes:
            original_occupancies = {}
            tmp_io_class_list = [i for i in io_classes if i != io_class]
            for i in tmp_io_class_list:
                original_occupancies[i.id] = get_io_class_occupancy(cache, i.id)

            io_count = get_io_count(io_class, cache_size, cache_line_size, io_size_multiplication)
            run_io_dir(f"{io_class.dir_path}/tmp_file", io_count)

            actual_occupancy = get_io_class_occupancy(cache, io_class.id)
            expected_occupancy = io_class.max_occupancy * cache_size
            if io_size_multiplication < 1:
                expected_occupancy *= io_size_multiplication
            expected_occupancy = expected_occupancy.align_down(cache_line_size.value.value)
            expected_occupancy.set_unit(Unit.Blocks4096)

            if not isclose(expected_occupancy.value, actual_occupancy.value, rel_tol=0.1):
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass {io_class.id} should be equal {expected_occupancy} "
                    f"but is {actual_occupancy} instead!"
                )

            for i in tmp_io_class_list:
                actual_occupancy = get_io_class_occupancy(cache, i.id)
                io_count = get_io_count(i, cache_size, cache_line_size, io_size_multiplication)
                if (
                    original_occupancies[i.id] != actual_occupancy
                    and io_count * Unit.Blocks4096.get_value() < actual_occupancy.value
                ):
                    TestRun.LOGGER.error(
                        f"Occupancy for ioclass {i.id} should not change "
                        f"during IO to ioclass {io_class.id}. Original value: "
                        f"{original_occupancies[i.id]}, actual: {actual_occupancy}"
                    )

    with TestRun.step("Check if none of ioclasses did not exceed specified occupancy"):
        for io_class in io_classes:
            actual_occupancy = get_io_class_occupancy(cache, io_class.id)

            occupancy_limit = (
                (io_class.max_occupancy * cache_size)
                .align_up(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            # Divergence may be caused by rounding max occupancy
            if actual_occupancy > occupancy_limit * 1.01:
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass id exceeded: {io_class.id}. "
                    f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
                )


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("io_size_multiplication", [0.5, 2])
def test_io_class_occupancy_directory_read(io_size_multiplication):
    """
    title: Test for max occupancy set for ioclass based on directory - read
    description: |
      Set cache mode to pass-through and create files on mounted core device.
      Switch cache to write through, and load io classes applying to different files.
      Read files and check if occupancy threshold is respected.
    pass_criteria:
      - Max occupancy is set correctly for each ioclass
      - Each ioclass does not exceed max occupancy
    """
    cache_line_size = CacheLineSize.LINE_64KiB
    cache_mode = CacheMode.WB

    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=cache_mode, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, 3, 0.10, f"{mountpoint}/A"),
            IoclassConfig(2, 4, 0.20, f"{mountpoint}/B"),
            IoclassConfig(3, 5, 0.30, f"{mountpoint}/C"),
        ]

        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step(
        f"In each directory create file with size of {io_size_multiplication} "
        f"max io_class occupancy for future read"
    ):
        for io_class in io_classes:
            io_size = get_io_count(io_class, cache_size, cache_line_size, io_size_multiplication)
            run_io_dir(f"{io_class.dir_path}/tmp_file", io_size)

    with TestRun.step("Remove old ioclass config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default io classes"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add io classes for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step("Reset cache stats"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Check initial occupancy"):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.LOGGER.error(
                    f"Incorrect initial occupancy for ioclass id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step(f"Read each file and check if data was inserted to appropriate ioclass"):
        for io_class in io_classes:
            original_occupancies = {}
            tmp_io_class_list = [i for i in io_classes if i != io_class]
            for i in tmp_io_class_list:
                original_occupancies[i.id] = get_io_class_occupancy(cache, i.id)

            run_io_dir_read(f"{io_class.dir_path}/tmp_file")

            actual_occupancy = get_io_class_occupancy(cache, io_class.id)

            expected_occupancy = io_class.max_occupancy * cache_size
            if io_size_multiplication < 1:
                expected_occupancy *= io_size_multiplication
            expected_occupancy.set_unit(Unit.Blocks4096)

            if not isclose(expected_occupancy.value, actual_occupancy.value, rel_tol=0.1):
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass {i.id} should be equal {expected_occupancy} "
                    f"but is {actual_occupancy} instead!"
                )

            for i in tmp_io_class_list:
                actual_occupancy = get_io_class_occupancy(cache, i.id)
                io_count = get_io_count(i, cache_size, cache_line_size, io_size_multiplication)
                if (
                    original_occupancies[i.id] != actual_occupancy
                    and io_count * Unit.Blocks4096.get_value() < actual_occupancy.value
                ):
                    TestRun.LOGGER.error(
                        f"Occupancy for ioclass {i.id} should not change "
                        f"during IO to ioclass {io_class.id}. Original value: "
                        f"{original_occupancies[i.id]}, actual: {actual_occupancy}"
                    )

    with TestRun.step("Check if none of ioclasses did not exceed specified occupancy"):
        for io_class in io_classes:
            actual_occupancy = get_io_class_occupancy(cache, io_class.id)

            occupancy_limit = (
                (io_class.max_occupancy * cache_size)
                .align_up(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            # Divergence may be caused by rounding max occupancy
            if actual_occupancy > occupancy_limit * 1.01:
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass id exceeded: {io_class.id}. "
                    f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
                )


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_occupancy_sum_cache():
    """
    title: Test for io classes occupancy sum
    description: |
      Create ioclass for 3 different directories, each with different
      max cache occupancy configured. Trigger IO to each ioclass and check
      if sum of their Usage stats is equal to cache Usage stats.
    pass_criteria:
      - Max occupancy is set correctly for each ioclass
      - Sum of io classes stats is equal to cache stats
    """
    with TestRun.step("Prepare CAS device"):
        cache, core = prepare()
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        default_ioclass_id = 0
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, 3, 0.10, f"{mountpoint}/A"),
            IoclassConfig(2, 4, 0.20, f"{mountpoint}/B"),
            IoclassConfig(3, 5, 0.30, f"{mountpoint}/C"),
        ]

        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old ioclass config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default io classes"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add ioclasses for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step("Purge cache"):
        cache.purge_cache()

    with TestRun.step("Verify stats before IO"):
        usage_stats_occupancy_sum = Size.zero()
        usage_stats_clean_sum = Size.zero()
        usage_stats_dirty_sum = Size.zero()

        all_io_class_usage_stats = []
        for i in io_classes:
            io_class_usage_stats = get_io_class_usage(cache, i.id)
            usage_stats_occupancy_sum += io_class_usage_stats.occupancy
            usage_stats_clean_sum += io_class_usage_stats.clean
            usage_stats_dirty_sum += io_class_usage_stats.dirty
            all_io_class_usage_stats.append(io_class_usage_stats)

        io_class_usage_stats = get_io_class_usage(cache, default_ioclass_id)
        usage_stats_occupancy_sum += io_class_usage_stats.occupancy
        usage_stats_clean_sum += io_class_usage_stats.clean
        usage_stats_dirty_sum += io_class_usage_stats.dirty

        cache_usage_stats = cache.get_statistics().usage_stats
        cache_usage_stats.free = Size.zero()

        if (
            cache_usage_stats.occupancy != usage_stats_occupancy_sum
            or cache_usage_stats.clean != usage_stats_clean_sum
            or cache_usage_stats.dirty != usage_stats_dirty_sum
        ):
            TestRun.LOGGER.error(
                "Initial cache usage stats doesn't match sum of io classes stats\n"
                f"Cache usage stats: {cache_usage_stats}\n"
                f"Usage stats occupancy sum: {usage_stats_occupancy_sum}\n"
                f"Usage stats clean sum: {usage_stats_clean_sum}\n"
                f"Usage stats dirty sum: {usage_stats_dirty_sum}\n"
                f"Particular stats {all_io_class_usage_stats}"
            )

    with TestRun.step(f"Trigger IO to each directory"):
        for io_class in io_classes:
            run_io_dir(
                f"{io_class.dir_path}/tmp_file",
                int((io_class.max_occupancy * cache_size) / Unit.Blocks4096.get_value()),
            )

    with TestRun.step("Verify stats after IO"):
        usage_stats_occupancy_sum = Size.zero()
        usage_stats_clean_sum = Size.zero()
        usage_stats_dirty_sum = Size.zero()

        all_io_class_usage_stats = []
        for i in io_classes:
            io_class_usage_stats = get_io_class_usage(cache, i.id)
            usage_stats_occupancy_sum += io_class_usage_stats.occupancy
            usage_stats_clean_sum += io_class_usage_stats.clean
            usage_stats_dirty_sum += io_class_usage_stats.dirty
            all_io_class_usage_stats.append(io_class_usage_stats)

        io_class_usage_stats = get_io_class_usage(cache, default_ioclass_id)
        usage_stats_occupancy_sum += io_class_usage_stats.occupancy
        usage_stats_clean_sum += io_class_usage_stats.clean
        usage_stats_dirty_sum += io_class_usage_stats.dirty

        cache_usage_stats = cache.get_statistics().usage_stats
        cache_usage_stats.free = Size.zero()

        if (
            cache_usage_stats.occupancy != usage_stats_occupancy_sum
            or cache_usage_stats.clean != usage_stats_clean_sum
            or cache_usage_stats.dirty != usage_stats_dirty_sum
        ):
            TestRun.LOGGER.error(
                "Initial cache usage stats doesn't match sum of io classes stats\n"
                f"Cache usage stats: {cache_usage_stats}\n"
                f"Usage stats occupancy sum: {usage_stats_occupancy_sum}\n"
                f"Usage stats clean sum: {usage_stats_clean_sum}\n"
                f"Usage stats dirty sum: {usage_stats_dirty_sum}\n"
                f"particular stats {all_io_class_usage_stats}"
            )


def get_io_count(io_class, cache_size, cls, io_size_multiplication):
    io_count = int((io_class.max_occupancy * cache_size) / Unit.Blocks4096 * io_size_multiplication)
    # io size needs to be aligned to cache line size
    io_count -= int(io_count % (cls.value / Unit.Blocks4096))

    return io_count
