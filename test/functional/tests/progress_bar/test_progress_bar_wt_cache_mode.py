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
test_file = "/test_file"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_progress_bar_wt_cache_mode():
    """
        title: Progress bar validation for WT cache mode.
        description: Validate the ability of the CAS to display data flushing progress
                     for Write-Through cache mode
        pass_criteria:
          - progress bar appear correctly
          - progress only increase
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(20, Unit.GibiByte)] * 4)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache in Write-Back mode and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(dev) for dev in core_devices]
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Make xfs filesystem on OpenCAS devices and mount it."):
        for i, core in enumerate(cores):
            core.create_filesystem(Filesystem.xfs)
            core.mount(f"{mount_point}{i}")

    with TestRun.step("Create 2 GiB file on OpenCAS devices."):
        for i, core in enumerate(cores):
            create_random_test_file(f"{mount_point}{i}{test_file}", Size(2, Unit.GibiByte))

    with TestRun.step("Change cache mode to Write-Through."):
        cache.set_cache_mode(CacheMode.WT, flush=False)

    with TestRun.step("Run command and check progress."):
        cmd = cli.flush_cache_cmd(str(cache.cache_id))
        check_progress_bar(cmd)
