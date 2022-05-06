#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta

import pytest
from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.casadm_parser import get_flushing_progress, wait_for_flushing
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_utils.filesystem.file import File
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_parallel_core_flushing():
    """
        title: Test for parallel cached volume flushing.
        description: Test checks whether all cores attached to one cache instance are flushed
                     in parallel after executing flush cache command.
        pass_criteria:
          - all cores should flushed in parallel
          - checksums for cores and core devices should be identical
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(8, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_partition_size = Size(2, Unit.GibiByte)
        core_disk.create_partitions([core_partition_size] * 4)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache in Write-Back mode and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
        cores = [cache.add_core(dev) for dev in core_devices]
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Run IO on each CAS device."):
        for core in cores:
            Dd().output(core.path)\
                .input("/dev/urandom")\
                .block_size(Size(1, Unit.Blocks4096))\
                .run()

    with TestRun.step("Check if occupancy of all CAS devices increased "
                      "and there is dirty data on them."):
        proper_stats = (0.9 * core_partition_size).set_unit(Unit.Blocks4096)
        occupancy = core.get_occupancy().set_unit(Unit.Blocks4096)
        dirty = core.get_dirty_blocks().set_unit(Unit.Blocks4096)
        for core in cores:
            if occupancy > proper_stats and dirty > proper_stats:
                TestRun.LOGGER.info(f"Stats are as expected for core {core.core_id}.")
            else:
                TestRun.fail(f"Stats are not as expected for core {core.core_id}\n"
                             f"Occupancy: {occupancy}\n"
                             f"Dirty: {dirty}\n"
                             f"Proper stats: {proper_stats}")

    with TestRun.step("In background run flush cache command."):
        pid = TestRun.executor.run_in_background(cli.flush_cache_cmd(str(cache.cache_id)))

    with TestRun.step("Check whether all CAS devices are in 'Flushing' state and wait for finish."):
        for core in cores:
            wait_for_flushing(cache, core, timedelta(seconds=10))

        percentages = [0] * len(cores)
        while TestRun.executor.check_if_process_exists(pid):
            current_values = get_progress(cache, cores)

            for old, new, core in zip(percentages, current_values, cores):
                if old > new:
                    TestRun.fail(f"Core {core.id}: progress decreased from {old}% to {new}%")

            percentages = current_values

    with TestRun.step("Check if amount of dirty data on each CAS device equals 0."):
        for core in cores:
            dirty_blocks = core.get_dirty_blocks()
            if dirty_blocks != Size.zero():
                TestRun.fail(f"Core {core.core_id} contain dirty data. "
                             f"Dirty blocks: {dirty_blocks}")

    with TestRun.step("Count checksums of each CAS device and check if it is identical "
                      "with checksum of core device associated with it."):

        TestRun.LOGGER.info("Calculate md5 for each core.")
        core_md5s = [File(core.path).md5sum() for core in cores]

        TestRun.LOGGER.info("Calculate md5 for each core device.")
        dev_md5s = [File(dev.path).md5sum() for dev in core_devices]

        TestRun.LOGGER.info("Compare md5 sums for cores and core devices.")
        for core_md5, dev_md5, core in zip(core_md5s, dev_md5s, cores):
            if core_md5 != dev_md5:
                TestRun.fail(f"MD5 sums of core {core.core_id} and core device do not match!")


def get_progress(cache, cores):
    progress = [0] * len(cores)
    for i, core in enumerate(cores):
        try:
            progress[i] = get_flushing_progress(cache.cache_id, core.core_id)
        except CmdException:
            progress[i] = 100
    return progress
