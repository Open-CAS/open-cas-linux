#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

mount_point = "/mnt/test"
test_file_path = f"{mount_point}/test_file"
test_file_tmp_path = "/tmp/filetmp"
test_file_size = Size(500, Unit.KiloByte)
files_number = 100


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.sata, DiskType.hdd]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.sata, DiskType.hdd]))
def test_raid_as_cache(cache_mode):
    """
        title: Test if SW RAID1 can be a cache device.
        description: |
          Test if SW RAID1 can be a cache for CAS device.
        pass_criteria:
          - Successful creation of RAID and building CAS device with it.
          - Files copied successfully, the md5sum match the origin one.
    """
    with TestRun.step("Create RAID1."):
        raid_disk = TestRun.disks['cache1']
        raid_disk.create_partitions([Size(2, Unit.GibiByte)])
        raid_disk_1 = raid_disk.partitions[0]
        raid_disk2 = TestRun.disks['cache2']
        raid_disk2.create_partitions([Size(2, Unit.GibiByte)])
        raid_disk_2 = raid_disk2.partitions[0]

        config = RaidConfiguration(
            level=Level.Raid1,
            metadata=MetadataVariant.Legacy,
            number_of_devices=2)

        raid_volume = Raid.create(config, [raid_disk_1, raid_disk_2])
        TestRun.LOGGER.info(f"RAID created successfully.")

    with TestRun.step("Prepare core device."):
        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Create CAS device with RAID1 as cache."):
        cache = casadm.start_cache(raid_volume, cache_mode, force=True)
        core = cache.add_core(core_dev)

        core.create_filesystem(Filesystem.ext3)
        core.mount(mount_point)

    with TestRun.step("Copy files to cache and check md5sum."):
        for i in range(0, files_number):
            test_file = fs_utils.create_random_test_file(test_file_tmp_path, test_file_size)
            test_file_copied = test_file.copy(test_file_path, force=True)

            if test_file.md5sum() != test_file_copied.md5sum():
                TestRun.LOGGER.error("Checksums are different.")

            fs_utils.remove(test_file.full_path, True)
            fs_utils.remove(test_file_copied.full_path, True)

        TestRun.LOGGER.info(f"Successful verification.")
