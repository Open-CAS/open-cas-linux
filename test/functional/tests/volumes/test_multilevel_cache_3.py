#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from api.cas.cache import CacheMode, casadm
from test_utils.size import Size, Unit
from test_tools.disk_utils import Filesystem
from .common import create_files_with_md5sums, compare_md5sums

mount_point = "/mnt/test"


@pytest.mark.require_disk("cache_1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache_2", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core_1", DiskTypeLowerThan("cache_1"))
@pytest.mark.require_disk("cache_3", DiskTypeSet([DiskType.hdd]))
def test_multilevel_cache_3():
    """
    title:
      Test multilevel cache.
    description:
      CAS Linux is able to use 3-level cache in different cache mode and remove it gracefully.
    pass_criteria:
      - Succesfully created 3-level cache.
      - Succesfully mounted filesystem on CAS device.
      - md5 sums are correct.
    """
    with TestRun.step("Prepare devices"):
        core_dev_1 = TestRun.disks["core_1"]

        cache_hdd = TestRun.disks["cache_3"]
        cache_hdd.create_partitions([Size(3.2, Unit.GibiByte)])
        cache_hdd = cache_hdd.partitions[0]

        cache_dev_1 = TestRun.disks["cache_1"]
        cache_dev_1.create_partitions([Size(3.2, Unit.GibiByte)])
        cache_dev_1 = cache_dev_1.partitions[0]

        cache_dev_2 = TestRun.disks["cache_2"]
        cache_dev_2.create_partitions([Size(3.2, Unit.GibiByte)])
        cache_dev_2 = cache_dev_2.partitions[0]

    with TestRun.step("Create cache in WT mode and add core to it"):
        cache_WT = casadm.start_cache(cache_dev=cache_dev_1, cache_mode=CacheMode.WT)
        core_WT = cache_WT.add_core(core_dev=core_dev_1)

    with TestRun.step("Create second layer cache in WB mode"):
        cache_WB = casadm.start_cache(cache_dev=cache_dev_2, cache_mode=CacheMode.WB)

    with TestRun.step("Add first CAS device by setting exported object as core to second layer"):
        core_WB = cache_WB.add_core(core_WT)

    with TestRun.step("Create third layer cache in WA mode"):
        cache_WA = casadm.start_cache(cache_dev=cache_hdd, cache_mode=CacheMode.WA)

    with TestRun.step("Add second CAS device by setting exported object as core to third layer"):
        core = cache_WA.add_core(core_WB)

    with TestRun.step("Create and mount filesystem on third CAS device"):
        core.create_filesystem(Filesystem.ext3, blocksize=int(Size(1, Unit.Blocks4096)))
        core.mount(mount_point)

    with TestRun.step("Create files and copy them to mounted directory"):
        md5_sums = create_files_with_md5sums(mount_point, 100)
    with TestRun.step(
        """Compare md5 susms between original files, files on IntelCAS device
        and files copied from intelCAS device"""
    ):
        compare_md5sums(md5_sums, mount_point, copy_to_tmp=True)
