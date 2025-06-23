#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from api.cas.cache import CacheMode, casadm
from type_def.size import Size, Unit
from test_tools.fs_tools import Filesystem
from common import create_files_with_md5sums, compare_md5sums


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_triple_level_cache():
    """
    title: Test for triple level cache.
    description: |
        Test if cache can be used as core of other cache up to three levels
    pass_criteria:
      - System does not crash.
      - Successfully created triple level cache.
      - Successfully mounted filesystem on CAS device.
      - Data consistency is being preserved.
    """
    mount_point = "/mnt/cas"

    with TestRun.step("Prepare devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(4, Unit.GibiByte)] * 3)
        core_dev.create_partitions([Size(4, Unit.GibiByte)])

        cache_hdd = core_dev.partitions[0]
        cache_partition_0 = cache_dev.partitions[0]
        cache_partition_1 = cache_dev.partitions[1]
        cache_partition_2 = cache_dev.partitions[2]

    with TestRun.step("Create cache in WT mode and add core to it"):
        first_level = casadm.start_cache(cache_dev=cache_partition_0, cache_mode=CacheMode.WT)
        core_WT = first_level.add_core(core_dev=cache_partition_1)

    with TestRun.step("Create second layer cache in WB mode"):
        second_level = casadm.start_cache(
            cache_dev=cache_partition_2, cache_mode=CacheMode.WB, force=True
        )

    with TestRun.step("Add first CAS device by setting exported object as core to second layer"):
        core_WB = second_level.add_core(core_WT)

    with TestRun.step("Create third layer cache in WA mode"):
        third_level = casadm.start_cache(cache_dev=cache_hdd, cache_mode=CacheMode.WA)

    with TestRun.step("Add second CAS device by setting exported object as core to third layer"):
        core = third_level.add_core(core_WB)

    with TestRun.step("Create filesystem on third-level`s core device and mount it"):
        core.create_filesystem(Filesystem.ext3, blocksize=int(Size(1, Unit.Blocks4096)))
        core.mount(mount_point)

    with TestRun.step("Create file on exported object"):
        md5_sums = create_files_with_md5sums(mount_point, 100)

    with TestRun.step("Check md5 sums between original file and exported object"):
        compare_md5sums(md5_sums, mount_point, copy_to_tmp=True)
