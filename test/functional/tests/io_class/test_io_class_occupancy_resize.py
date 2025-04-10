#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from recordclass import recordclass

from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.ioclass_config import IoClass, default_config_file_path
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_tools import Filesystem, create_directory
from test_tools.os_tools import sync
from test_tools.udev import Udev
from type_def.size import Unit
from tests.io_class.io_class_common import (
    mountpoint,
    prepare,
    get_io_class_occupancy,
    run_io_dir,
)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrize("new_occupancy", [25, 50, 70, 100])
def test_ioclass_resize(cache_line_size, new_occupancy):
    """
    title: Resize ioclass
    description: |
      Add ioclass, fill it with data, change it's size and check if new
      limit is respected
    pass_criteria:
      - Occupancy threshold is respected
    """
    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=CacheMode.WT, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = recordclass("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_class = IoclassConfig(2, 3, 0.10, f"{mountpoint}/A")

        create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old ioclass config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default io classes"):
        ioclass_config.add_ioclass(
            ioclass_id=1,
            rule="metadata&done",
            eviction_priority=1,
            allocation="1.00",
            ioclass_config_path=default_config_file_path,
        )
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add directory for ioclass"):
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
        occupancy = get_io_class_occupancy(cache, io_class.id)
        if occupancy.get_value() != 0:
            TestRun.LOGGER.error(
                f"Incorrect initial occupancy for ioclass id: {io_class.id}."
                f" Expected 0, got: {occupancy}"
            )

    with TestRun.step(f"Perform IO with size equal to cache size"):
        run_io_dir(f"{io_class.dir_path}/tmp_file", int(cache_size / Unit.Blocks4096))

    with TestRun.step("Check if the ioclass did not exceed specified occupancy"):
        actual_occupancy = get_io_class_occupancy(cache, io_class.id)

        occupancy_limit = (
            (io_class.max_occupancy * cache_size)
            .align_up(Unit.Blocks4096.get_value())
            .set_unit(Unit.Blocks4096)
        )

        # Divergence may be caused be rounding max occupancy
        if actual_occupancy > occupancy_limit * 1.01:
            TestRun.LOGGER.error(
                f"Occupancy for ioclass id exceeded: {io_class.id}. "
                f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
            )

    with TestRun.step(
        f"Resize ioclass from {io_class.max_occupancy * 100}% to {new_occupancy}%"
        " cache occupancy"
    ):
        io_class.max_occupancy = new_occupancy / 100
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

        ioclass_config.add_ioclass(
            ioclass_id=1,
            rule="metadata&done",
            eviction_priority=1,
            allocation="1.00",
            ioclass_config_path=default_config_file_path,
        )
        ioclass_config.add_ioclass(
            io_class.id,
            f"directory:{io_class.dir_path}&done",
            io_class.eviction_prio,
            f"{io_class.max_occupancy:0.2f}",
        )

        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step(f"Perform IO with size equal to cache size"):
        run_io_dir(f"{io_class.dir_path}/tmp_file", int(cache_size / Unit.Blocks4096))

    with TestRun.step("Check if the ioclass did not exceed specified occupancy"):
        actual_occupancy = get_io_class_occupancy(cache, io_class.id)

        occupancy_limit = (
            (io_class.max_occupancy * cache_size)
            .align_up(Unit.Blocks4096.get_value())
            .set_unit(Unit.Blocks4096)
        )

        # Divergence may be caused be rounding max occupancy
        if actual_occupancy > occupancy_limit * 1.01:
            TestRun.LOGGER.error(
                f"Occupancy for ioclass id exceeded: {io_class.id}. "
                f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
            )
