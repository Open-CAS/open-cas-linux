#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from collections import namedtuple
from math import isclose
from api.cas import ioclass_config, casadm
from tests.io_class.io_class_common import prepare, mountpoint, TestRun, Unit, \
    ioclass_config_path, run_io_dir, get_io_class_dirty, get_io_class_usage, get_io_class_occupancy
from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.ioclass_config import IoClass
from storage_devices.device import Device
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.os_utils import sync, Udev


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_ioclass_occuppancy_load(cache_line_size):
    """
        title: Load cache with occupancy limit specified
        description: |
          Load cache and verify if occupancy limits are loaded correctly and if
          each part has assigned apropriate number of
          dirty blocks.
        pass_criteria:
          - Occupancy thresholds have correct values for each ioclass after load
    """
    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=CacheMode.WB, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(
        f"Prepare filesystem and mount {core.path} at {mountpoint}"
    ):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple(
            "IoclassConfig", "id eviction_prio max_occupancy dir_path"
        )
        io_classes = [
            IoclassConfig(1, 3, 0.30, f"{mountpoint}/A"),
            IoclassConfig(2, 3, 0.30, f"{mountpoint}/B"),
            IoclassConfig(3, 3, 0.30, f"{mountpoint}/C"),
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

    with TestRun.step(f"Perform IO with size equal to cache size"):
        for io_class in io_classes:
            run_io_dir(
                f"{io_class.dir_path}/tmp_file", int((cache_size) / Unit.Blocks4096)
            )

    with TestRun.step("Check if the ioclass did not exceed specified occupancy"):
        for io_class in io_classes:
            actuall_dirty = get_io_class_dirty(cache, io_class.id)

            dirty_limit = (
                (io_class.max_occupancy * cache_size)
                .align_down(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            if not isclose(
                actuall_dirty.get_value(), dirty_limit.get_value(), rel_tol=0.1
            ):
                TestRun.LOGGER.error(
                    f"Dirty for ioclass id: {io_class.id} doesn't match expected."
                    f"Expected: {dirty_limit}, actuall: {actuall_dirty}"
                )

    with TestRun.step("Stop cache without flushing the data"):
        original_usage_stats = {}
        for io_class in io_classes:
            original_usage_stats[io_class.id] = get_io_class_usage(cache, io_class.id)

        original_ioclass_list = cache.list_io_classes()
        cache_disk_path = cache.cache_device.path
        core.unmount()
        cache.stop(no_data_flush=True)

    with TestRun.step("Load cache"):
        cache = casadm.start_cache(Device(cache_disk_path), load=True)

    with TestRun.step("Check if the ioclass did not exceed specified occupancy"):
        for io_class in io_classes:
            actuall_dirty = get_io_class_dirty(cache, io_class.id)

            dirty_limit = (
                (io_class.max_occupancy * cache_size)
                .align_down(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            if not isclose(
                actuall_dirty.get_value(), dirty_limit.get_value(), rel_tol=0.1
            ):
                TestRun.LOGGER.error(
                    f"Dirty for ioclass id: {io_class.id} doesn't match expected."
                    f"Expected: {dirty_limit}, actuall: {actuall_dirty}"
                )

    with TestRun.step("Compare ioclass configs"):
        ioclass_list_after_load = cache.list_io_classes()

        if len(ioclass_list_after_load) != len(original_ioclass_list):
            TestRun.LOGGER.error(
                f"Ioclass occupancy limit doesn't match. Original list size: "
                f"{len(original_ioclass_list)}, loaded list size: "
                f"{len(ioclass_list_after_load)}"
            )

        original_sorted = sorted(original_ioclass_list, key=lambda k: k.id)
        loaded_sorted = sorted(ioclass_list_after_load, key=lambda k: k.id)

        for original, loaded in zip(original_sorted, loaded_sorted):
            original_allocation = original.allocation
            loaded_allocation = loaded.allocation
            ioclass_id = original.id
            if original_allocation != loaded_allocation:
                TestRun.LOGGER.error(
                    f"Occupancy limit doesn't match for ioclass {ioclass_id}: "
                    f"Original: {original_allocation}, loaded: {loaded_allocation}"
                )

    with TestRun.step("Compare usage stats before and after the load"):
        for io_class in io_classes:
            actuall_usage_stats = get_io_class_usage(cache, io_class.id)
            if original_usage_stats[io_class.id] != actuall_usage_stats:
                TestRun.LOGGER.error(
                    f"Usage stats doesn't match for ioclass {io_class.id}. "
                    f"Original: {original_usage_stats[io_class.id]}, "
                    f"loaded: {actuall_usage_stats}"
                )
