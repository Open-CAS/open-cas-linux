#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
import pytest
from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, CleaningPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.ddrescue import Ddrescue
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("filesystem", [Filesystem.ext4, Filesystem.xfs])
@pytest.mark.parametrizex("cleaning", [CleaningPolicy.alru, CleaningPolicy.nop])
def test_trim_eviction(cache_mode, cache_line_size, filesystem, cleaning):
    """
        title: Test verifying if trim requests do not cause eviction on CAS device.
        description: |
          When trim requests enabled and files are being added and removed from CAS device,
          there is no eviction (no reads from cache).
        pass_criteria:
          - Reads from cache device are the same before and after removing test file.
    """
    mount_point = "/mnt"
    test_file_path = os.path.join(mount_point, "test_file")

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Start cache on device supporting trim and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size)
        cache.set_cleaning_policy(cleaning)
        Udev.disable()
        core = cache.add_core(core_dev)

    with TestRun.step("Create filesystem on CAS device and mount it."):
        core.create_filesystem(filesystem)
        core.mount(mount_point, ["discard"])

    with TestRun.step("Create random file using ddrescue."):
        test_file = fs_utils.create_random_test_file(test_file_path, core_dev.size * 0.9)
        create_file_with_ddrescue(core_dev, test_file)

    with TestRun.step("Remove file and create a new one."):
        cache_iostats_before = cache_dev.get_io_stats()
        test_file.remove()
        os_utils.sync()
        os_utils.drop_caches()
        create_file_with_ddrescue(core_dev, test_file)

    with TestRun.step("Check using iostat that reads from cache did not occur."):
        cache_iostats_after = cache_dev.get_io_stats()
        reads_before = cache_iostats_before.sectors_read
        reads_after = cache_iostats_after.sectors_read

        if reads_after != reads_before:
            TestRun.fail(f"Number of reads from cache before and after removing test file "
                         f"differs. Reads before: {reads_before}, reads after: {reads_after}.")
        else:
            TestRun.LOGGER.info(
                "Number of reads from cache before and after removing test file is the same.")


def create_file_with_ddrescue(core_dev, test_file):
    ddrescue = Ddrescue() \
        .block_size(Size(1, Unit.Blocks4096)) \
        .size(core_dev.size * 0.9) \
        .synchronous() \
        .source("/dev/urandom") \
        .destination(test_file.full_path)
    ddrescue.run()
