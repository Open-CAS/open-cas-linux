#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from collections import namedtuple
from math import isclose

import pytest

from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from .io_class_common import *


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_eviction_priority():
    """
    title: Check whether eviction priorities are respected.
    description: |
      Create io class for 4 different directories, each with different
      eviction priority configured. Saturate 3 of them and check if the
      partitions are evicted in a good order during IO to the fourth
    pass_criteria:
      - Partitions are evicted in specified order
    """
    cache_line_size = CacheLineSize.LINE_64KiB

    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=CacheMode.WT, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Preparing filesystem and mounting {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, 3, 0.30, f"{mountpoint}/A"),
            IoclassConfig(2, 4, 0.30, f"{mountpoint}/B"),
            IoclassConfig(3, 5, 0.40, f"{mountpoint}/C"),
            IoclassConfig(4, 1, 1.00, f"{mountpoint}/D"),
        ]
        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Adding io classes for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
                ioclass_config_path
            )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Resetting cache stats"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Checking initial occupancy"):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.LOGGER.error(
                    f"Incorrect initial occupancy for io class id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step(f"To A, B and C directories perform IO with size of max io_class occupancy"):
        for io_class in io_classes[0:3]:
            run_io_dir(
                f"{io_class.dir_path}/tmp_file",
                int((io_class.max_occupancy * cache_size) / Unit.Blocks4096.get_value()),
            )

    with TestRun.step("Check if each io class reached it's occupancy limit"):
        for io_class in io_classes[0:3]:
            actual_occupancy = get_io_class_occupancy(cache, io_class.id)

            occupancy_limit = (
                (io_class.max_occupancy * cache_size)
                .align_down(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            if not isclose(actual_occupancy.value, occupancy_limit.value, rel_tol=0.1):
                TestRun.LOGGER.error(
                    f"Occupancy for io class {io_class.id} does not match. "
                    f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
                )

        if get_io_class_occupancy(cache, io_classes[3].id).value != 0:
            TestRun.LOGGER.error(
                f"Occupancy for io class {io_classes[3].id} should be 0. "
                f"Actual: {actual_occupancy}"
            )

    with TestRun.step(
        "Perform IO to the fourth directory and check "
        "if other partitions are evicted in a good order"
    ):
        target_io_class = io_classes[3]
        io_classes_to_evict = io_classes[:3][::-1]  # List is ordered by eviction priority
        io_classes_evicted = []
        io_offset = 0
        for io_class in io_classes_to_evict:
            io_size = int((io_class.max_occupancy * cache_size) / Unit.Blocks4096.get_value())
            run_io_dir(f"{target_io_class.dir_path}/tmp_file_{io_class.id}", io_size, io_offset)
            io_offset += io_size
            part_to_evict_end_occupancy = get_io_class_occupancy(cache, io_class.id, percent=True)

            # Since number of evicted cache lines is always >= 128, occupancy is checked
            # with approximation
            if not isclose(part_to_evict_end_occupancy, 0, abs_tol=4):
                TestRun.LOGGER.error(
                    f"Wrong percent of cache lines evicted from part {io_class.id}. "
                    f"Meant to be evicted {io_class.max_occupancy * 100}%, actaully evicted "
                    f"{io_class.max_occupancy * 100 - part_to_evict_end_occupancy}%"
                )

            io_classes_evicted.append(io_class)

            for i in io_classes_to_evict:
                if i in io_classes_evicted:
                    continue

                occupancy = get_io_class_occupancy(cache, i.id, percent=True)

                if not isclose(occupancy, i.max_occupancy * 100, abs_tol=4):
                    TestRun.LOGGER.error(f"Io class {i.id} evicted incorrectly")
