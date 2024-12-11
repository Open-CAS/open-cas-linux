#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from collections import namedtuple
from math import isclose

import test_tools.fs_tools
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from api.cas.ioclass_config import IoClass, default_config_file_path
from test_tools import fs_tools
from test_tools.fs_tools import Filesystem
from core.test_run import TestRun
from type_def.size import Size, Unit
from .io_class_common import (
    prepare,
    mountpoint,
    get_io_class_occupancy,
    run_io_dir,
)
from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CacheLineSize

cache_size = Size(256, Unit.MiB)
core_size = Size(2, Unit.GiB)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_pinning_eviction():
    """
    title: IO class pinning eviction - stress.
    description: |
        Check Open CAS ability to prevent from eviction of pinned IoClass - stress test.
    pass_criteria:
        - IoClasses loaded successfully
        - Pinned class occupies the same ammount of cache after each IO operation on different IoClass
    """

    with TestRun.step("Prepare devices"):
        cache, core = prepare(core_size=core_size, cache_size=cache_size, cache_mode=CacheMode.WT)
        cache_line_count = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Mount filesystem"):
        test_tools.fs_utils.create_filesystem(Filesystem.xfs)
        core.mount(mountpoint)

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, "", 0.60, f"{mountpoint}/A"),
            IoclassConfig(2, 10, 0.70, f"{mountpoint}/B"),
            IoclassConfig(3, 40, 0.80, f"{mountpoint}/C"),
            IoclassConfig(4, 50, 0.90, f"{mountpoint}/D"),
            IoclassConfig(5, 100, 0.70, f"{mountpoint}/E"),
        ]

        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default ioclasses"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add IoClasses for dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy:0.2f}",
            )
        pinned_io_class = io_classes[0]
        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step("Reset cache stats"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Check occupancy "):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.fail(
                    f"Incorrect inital occupancy for ioclass id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step(f"Trigger IO to pinned class directory"):
        run_io_dir(
            f"{pinned_io_class.dir_path}/tmp_file",
            int((pinned_io_class.max_occupancy * cache_line_count) / Unit.Blocks4096),
        )
        pinned_occupancy = get_io_class_occupancy(cache, pinned_io_class.id)

        expected_occupancy = pinned_io_class.max_occupancy * cache_line_count
        expected_occupancy = expected_occupancy.align_down(CacheLineSize.LINE_4KiB.value.value)
        expected_occupancy.set_unit(Unit.Blocks4096)

        if not isclose(pinned_occupancy.value, expected_occupancy.value, rel_tol=0.01):
            TestRun.fail(
                "Pinned IoClass occupancy is not close equal to expected value."
                f"Expected: {expected_occupancy} Actual: {pinned_occupancy} "
            )

    with TestRun.step(
        "Trigger IO to the rest IoClasses directories and check if pinned class occupancy changes"
    ):
        for io_class in io_classes[1:]:
            run_io_dir(
                f"{io_class.dir_path}/tmp_file",
                int((io_class.max_occupancy * cache_size) / Unit.Blocks4096),
            )
            after_op_occupancy = get_io_class_occupancy(cache, pinned_io_class.id)
            if pinned_occupancy != after_op_occupancy:
                TestRun.fail(
                    f"Pinned IO class do not occupy all of their space. Expected:{pinned_occupancy} Actual:{after_op_occupancy}"
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_pinned_ioclasses_eviction():
    """
    title: IO class pinning eviction - two pinned classes.
    description:
        Check Open CAS ability to prevent from eviction of pinned IoClass when writing
        into another pinned IoClass.
    pass_criteria:
        - IoClasses loaded successfully
        - First pinned class occupies the same ammount of cache after IO operation on another pinned IoClass
    """

    with TestRun.step("Prepare devices"):
        cache, core = prepare(core_size=core_size, cache_size=cache_size)
        cache_line_count = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Mount filesystem"):
        test_tools.fs_utils.create_filesystem(Filesystem.xfs)
        core.mount(mountpoint)

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, "", 0.1, f"{mountpoint}/A"),
            IoclassConfig(2, "", 1.0, f"{mountpoint}/B"),
        ]

        for io_class in io_classes:
            fs_utils.create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default ioclasses"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="0.00")).split(","))

    with TestRun.step("Add IoClasses for dirs"):
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

    with TestRun.step("Check occupancy "):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.fail(
                    f"Incorrect inital occupancy for ioclass id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step(f"Trigger IO to first pinned class directory"):
        run_io_dir(
            f"{io_classes[0].dir_path}/tmp_file",
            int((io_classes[0].max_occupancy * cache_size) / Unit.Blocks4096),
        )
        first_io_pinned_occupancy = get_io_class_occupancy(cache, io_classes[0].id)

        expected_occupancy = io_classes[0].max_occupancy * cache_line_count
        expected_occupancy = expected_occupancy.align_down(CacheLineSize.LINE_4KiB.value.value)
        expected_occupancy.set_unit(Unit.Blocks4096)

        if not isclose(first_io_pinned_occupancy.value, expected_occupancy.value, rel_tol=0.01):
            TestRun.fail(
                "Pinned IoClass occupancy is not close equal to expected value."
                f"Expected: {expected_occupancy} Actual: {first_io_pinned_occupancy} "
            )

    with TestRun.step(f"Trigger IO to second pinned class directory"):
        run_io_dir(
            f"{io_classes[1].dir_path}/tmp_file",
            int((io_classes[1].max_occupancy * cache_size) / Unit.Blocks4096),
        )
        after_op_occupancy = get_io_class_occupancy(cache, io_classes[0].id)

    with TestRun.step("Compare if occupancy has changed on smaller pinned class"):
        if first_io_pinned_occupancy != after_op_occupancy:
            TestRun.fail(
                f"Pinned ioclass shouldn't get evicted."
                f"Expected occupancy: {first_io_pinned_occupancy} Actual: {after_op_occupancy}"
            )
