#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from test_tools.disk_utils import Filesystem
from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_utils.os_utils import sync, Udev, drop_caches
from test_utils.size import Unit, Size
from core.test_run import TestRun


dd_bs = Size(1, Unit.Blocks4096)
dd_count = 1230
cached_mountpoint = "/tmp/ioclass_core_id_test/cached"
not_cached_mountpoint = "/tmp/ioclass_core_id_test/not_cached"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", [fs for fs in Filesystem] + [None])
def test_ioclass_core_id(filesystem):
    """
    title: Test for `core_id` classification rule
    description: |
        Test if IO to core with selective allocation enabled is cached and IO to core with
        selective allocation disabled is redirected to pass-through mode
    pass_criteria:
     - IO to core with enabled selective allocation is cached
     - IO to core with disabled selective allocation is not cached
    """
    fs_info = f"with {filesystem}" if filesystem else ""
    with TestRun.step(
        f"Start cache with two cores on created partitions {fs_info}, "
        "with NOP, disabled seq cutoff"
    ):
        cache, cores = prepare(filesystem, 2)
        core_1, core_2 = cores[0], cores[1]

    with TestRun.step(f"Add core_id based classification rules"):
        cached_ioclass_id = 11
        not_cached_ioclass_id = 12

        ioclass_config.add_ioclass(
            ioclass_id=cached_ioclass_id,
            eviction_priority=22,
            allocation="1.00",
            rule=f"core_id:eq:{core_1.core_id}&done",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=not_cached_ioclass_id,
            eviction_priority=22,
            allocation="0.00",
            rule=f"core_id:eq:{core_2.core_id}&done",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )

    with TestRun.step(f"Load ioclass config file"):
        casadm.load_io_classes(
            cache_id=cache.cache_id, file=ioclass_config.default_config_file_path
        )

    if filesystem:
        with TestRun.step(f"Mount cores"):
            core_1.mount(cached_mountpoint)
            core_2.mount(not_cached_mountpoint)

    with TestRun.step(f"Reset counters"):
        sync()
        drop_caches()
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step(f"Trigger IO to both cores"):
        if filesystem:
            dd_dst_paths = [cached_mountpoint + "/test_file", not_cached_mountpoint + "/test_file"]
        else:
            dd_dst_paths = [core_1.path, core_2.path]

        for path in dd_dst_paths:
            dd = (
                Dd()
                .input("/dev/zero")
                .output(path)
                .count(dd_count)
                .block_size(dd_bs)
                .oflag("sync")
            )
            dd.run()
        sync()
        drop_caches()

    with TestRun.step(f"Check cores occupancy"):
        dd_size = (dd_bs * dd_count).set_unit(Unit.Blocks4096)

        core_1_occupancy = core_1.get_statistics().usage_stats.occupancy
        core_2_occupancy = core_2.get_statistics().usage_stats.occupancy

        if core_1_occupancy < dd_size:
            TestRun.LOGGER.error(
                f"First core's occupancy is {core_1_occupancy} "
                f"- it is less than {dd_size} - triggerd IO size!"
            )

        if core_2_occupancy.get_value() != 0:
            TestRun.LOGGER.error(f"First core's occupancy is {core_2_occupancy} instead of 0!")

    with TestRun.step(f"Check ioclasses occupancy"):
        cached_ioclass_occupancy = cache.get_io_class_statistics(
            io_class_id=cached_ioclass_id
        ).usage_stats.occupancy
        not_cached_ioclass_occupancy = cache.get_io_class_statistics(
            io_class_id=not_cached_ioclass_id
        ).usage_stats.occupancy

        if cached_ioclass_occupancy < dd_size:
            TestRun.LOGGER.error(
                f"Cached ioclass occupancy is {cached_ioclass_occupancy} "
                f"- it is less than {dd_size} - triggerd IO size!"
            )
        if not_cached_ioclass_occupancy.get_value() != 0:
            TestRun.LOGGER.error(
                f"Not cached ioclass occupancy is {not_cached_ioclass_occupancy} instead of 0!"
            )

    with TestRun.step(f"Check number of serviced requests to not cached core"):
        core_2_serviced_requests = core_2.get_statistics().request_stats.requests_serviced
        if core_2_serviced_requests != 0:
            TestRun.LOGGER.error(
                f"Second core should have 0 serviced requests "
                f"instead of {core_2_serviced_requests}"
            )


def prepare(filesystem, cores_number):
    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    cache_device.create_partitions([Size(10, Unit.GibiByte)])
    core_device.create_partitions([Size(5, Unit.GibiByte)] * cores_number)

    cache_device = cache_device.partitions[0]

    cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WT, force=True)

    Udev.disable()
    casadm.set_param_cleaning(cache_id=cache.cache_id, policy=CleaningPolicy.nop)

    cores = []
    for part in core_device.partitions:
        if filesystem:
            part.create_filesystem(filesystem)
        cores.append(casadm.add_core(cache, core_dev=part))

    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    ioclass_config.create_ioclass_config(
        add_default_rule=False, ioclass_config_path=ioclass_config.default_config_file_path
    )
    # To make test more precise all workload except of tested ioclass should be
    # put in pass-through mode
    ioclass_config.add_ioclass(
        ioclass_id=0,
        eviction_priority=22,
        allocation="1.00",
        rule="unclassified",
        ioclass_config_path=ioclass_config.default_config_file_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=1,
        eviction_priority=22,
        allocation="0.00",
        rule="metadata",
        ioclass_config_path=ioclass_config.default_config_file_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=2,
        eviction_priority=22,
        allocation="0.00",
        rule="direct",
        ioclass_config_path=ioclass_config.default_config_file_path,
    )

    return cache, cores
