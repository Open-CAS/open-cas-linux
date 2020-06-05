#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from collections import namedtuple
from math import isclose

import pytest

from .io_class_common import *
from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.ioclass_config import IoClass
from api.cas.statistics import UsageStats
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.os_utils import sync, Udev


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("io_size_multiplication", [0.5, 2])
@pytest.mark.parametrize("cache_mode", [CacheMode.WT, CacheMode.WB])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_ioclass_occupancy_directory_write(io_size_multiplication, cache_mode, cache_line_size):
    """
        title: Test for max occupancy set for ioclass based on directory
        description: |
          Create ioclass for 3 different directories, each with different
          max cache occupancy configured. Run IO against each directory and see
          if occupancy limit is repected.
        pass_criteria:
          - Max occupancy is set correctly for each ioclass
          - Each ioclass does not exceed max occupancy
    """
    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=cache_mode, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.system_path} at {mountpoint}"):
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

    with TestRun.step("Add default ioclasses"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add ioclasses for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

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
        f"To each directory perform IO with size of {io_size_multiplication} max io_class occupancy"
    ):
        for io_class in io_classes:
            original_occupacies = {}
            tmp_io_class_list = [i for i in io_classes if i != io_class]
            for i in tmp_io_class_list:
                original_occupacies[i.id] = get_io_class_occupancy(cache, i.id)

            run_io_dir(
                f"{io_class.dir_path}/tmp_file",
                int(
                    (io_class.max_occupancy * cache_size) / Unit.Blocks4096 * io_size_multiplication
                ),
            )

            actuall_occupancy = get_io_class_occupancy(cache, io_class.id)
            io_size = io_class.max_occupancy * cache_size
            if io_size_multiplication < 1:
                io_size *= io_size_multiplication
            io_size.set_unit(Unit.Blocks4096)

            if not isclose(io_size.value, actuall_occupancy.value, rel_tol=0.1):
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass {i.id} should be equal {io_size} "
                    f"but is {actuall_occupancy} instead!"
                )

            for i in tmp_io_class_list:
                actuall_occupancy = get_io_class_occupancy(cache, i.id)
                if original_occupacies[i.id] != actuall_occupancy:
                    TestRun.LOGGER.error(
                        f"Occupancy for ioclass {i.id} should not change "
                        f"during IO to ioclass {io_class.id}. Original value: "
                        f"{original_occupacies[i.id]}, actuall: {actuall_occupancy}"
                    )

    with TestRun.step("Check if none of ioclasses did not exceed specified occupancy"):
        for io_class in io_classes:
            actuall_occupancy = get_io_class_occupancy(cache, io_class.id)

            occupancy_limit = (
                (io_class.max_occupancy * cache_size)
                .align_up(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            # Divergency may be casued be rounding max occupancy
            if actuall_occupancy > occupancy_limit + Size(100, Unit.Blocks4096):
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass id exceeded: {io_class.id}. "
                    f"Limit: {occupancy_limit}, actuall: {actuall_occupancy}"
                )
