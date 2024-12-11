#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from collections import namedtuple
import pytest

from api.cas.ioclass_config import default_config_file_path
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from .io_class_common import ioclass_config, get_io_class_occupancy, run_io_dir
from api.cas import casadm
from test_tools.os_tools import sync, drop_caches
from test_tools.udev import Udev
from type_def.size import Unit, Size


cache_size = Size(100, Unit.MiB)
core_size = Size(500, Unit.MiB)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_eviction_pinned_after_unpin():
    """
    title: Test if pinned classes after unpinning can be evicted.
    description:
        Create two IO classes, one pinned and one with given priority.
        Check if eviction does not occur on pinned IO class after performing writes
        on both IO classes. After that unpin pinned IO class, peform writes on second IO class
        and check if eviction occured on unpinned IO class.
    pass_criteria:
        - pinned IO class after unpinning is getting evicted after performing writes on other
        IO class.
    """
    with TestRun.step("Prepare CAS devices"):
        cache, cores = prepare(cores_number=2, cache_size=cache_size, core_size=core_size)
        cache_line_count = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Add IoClasses for cores"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy core")
        io_classes = [IoclassConfig(1, "", 1, cores[0]), IoclassConfig(2, 10, 1, cores[1])]
        _add_and_load_io_classes(cache.cache_id, io_classes)
        pinned_io_class = io_classes[0]

    with TestRun.step("Reset cache stats"):
        _refresh_cache(cache)

    with TestRun.step("Check occupancy before fio"):
        occupancy_before = get_io_class_occupancy(cache, pinned_io_class.id)
        if occupancy_before.get_value() != 0:
            TestRun.fail(
                f"Incorrect inital occupancy for pinned ioclass: {pinned_io_class.id}."
                f" Expected 0, got: {occupancy_before}"
            )

    with TestRun.step("Run IO on pinned IO class"):
        run_io_dir(f"{pinned_io_class.core.path}", int(cache_line_count / Unit.Blocks4096))
        occupancy_after = get_io_class_occupancy(cache, pinned_io_class.id, percent=True)

    with TestRun.step("Unpin ioclass to and set its priority to be lower than second IO class"):
        io_classes = [IoclassConfig(1, 11, 1, cores[0]), IoclassConfig(2, 10, 1, cores[1])]
        _add_and_load_io_classes(cache.cache_id, io_classes)

    with TestRun.step("Run dd on second io ioclass "):
        run_io_dir(f"{io_classes[1].core.path}", int(cache_line_count / Unit.Blocks4096))

    with TestRun.step("Check if data from 'was pinned' IO class was evicted"):
        occupancy_after_change = get_io_class_occupancy(cache, pinned_io_class.id, percent=True)

        if 0 != occupancy_after_change:
            TestRun.fail(
                f"""
                Data was not evicted: before:  {occupancy_after}
                after: {occupancy_after_change}
                """
            )


def _refresh_cache(cache):
    sync()
    drop_caches()
    cache.purge_cache()
    cache.reset_counters()


def _add_and_load_io_classes(cache_id, io_classes: list):
    ioclass_config.remove_ioclass_config()
    ioclass_config.create_ioclass_config(False)

    for io_class in io_classes:
        ioclass_config.add_ioclass(
            ioclass_id=io_class.id,
            rule=f"core_id:eq:{io_class.core.core_id}&done",
            eviction_priority=io_class.eviction_prio,
            allocation=f"{io_class.max_occupancy:0.2f}",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )

    casadm.load_io_classes(cache_id=cache_id, file=default_config_file_path)


def prepare(cores_number=1, cache_size=Size(10, Unit.GibiByte), core_size=Size(5, Unit.GibiByte)):

    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    cache_device.create_partitions([cache_size])
    core_device.create_partitions([core_size] * cores_number)

    cache_device = cache_device.partitions[0]

    cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WT, force=True)

    Udev.disable()
    casadm.set_param_cleaning(cache_id=cache.cache_id, policy=CleaningPolicy.nop)

    cores = []
    for part in core_device.partitions:
        cores.append(casadm.add_core(cache, core_dev=part))

    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
    for core in cores:
        core.set_seq_cutoff_policy(SeqCutOffPolicy.never)
    return cache, cores
