#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.progress_bar import check_progress_bar
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.disk_utils import Filesystem
from test_tools.fs_utils import create_random_test_file
from test_utils.size import Size, Unit


mount_point = "/mnt/test"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_progress_bar_big_files():
    """
        title: Progress bar validation for big files.
        description: Validate the ability of the CAS to display data flushing progress
                     for big amount of dirty data.
        pass_criteria:
          - progress bar appear correctly
          - progress only increase
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(20, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Start cache in Write-Back mode and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        core = cache.add_core(core_dev)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Make xfs filesystem on OpenCAS device and mount it."):
        core.create_filesystem(Filesystem.xfs)
        core.mount(mount_point)

    with TestRun.step("Create file on OpenCAS device."):
        create_random_test_file(test_file_path, cache.size + Size(1, Unit.GibiByte))

    with TestRun.step("Run command and check progress."):
        cmd = cli.flush_cache_cmd(str(cache.cache_id))
        check_progress_bar(cmd)
