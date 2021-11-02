#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

mount_point = "/mnt/test"
mount_point2 = "/mnt/test2"
test_file_path = f"{mount_point}/test_file"
test_file_tmp_path = "/tmp/filetmp"
test_file_size = Size(500, Unit.KiloByte)
test_file_size_small = Size(1, Unit.KibiByte)
number_of_files = 100


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
        for i in range(0, number_of_files):
            test_file = fs_utils.create_random_test_file(test_file_tmp_path, test_file_size)
            test_file_copied = test_file.copy(test_file_path, force=True)

            if test_file.md5sum() != test_file_copied.md5sum():
                TestRun.LOGGER.error("Checksums are different.")

            fs_utils.remove(test_file.full_path, True)
            fs_utils.remove(test_file_copied.full_path, True)

        TestRun.LOGGER.info(f"Successful verification.")


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache1"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache1"))
def test_many_cores_raid_as_cache(cache_mode):
    """
        title: Test if CAS is working with many core devices using RAID0 as cache device.
        description: |
          Test if CAS is working properly with many core devices using RAID0 as cache device
           and verification of data integrity of files copied to cores.
        pass_criteria:
          - No system crash.
          - Successful creation of RAID0 and using it as cache for CAS device
          - Successful addition of first and second core to CAS device
          - Successful creation and copy files to each core and verification of theirs md5sum.
    """
    with TestRun.step("Create cache with RAID0 as caching device."):
        raid_disk = TestRun.disks['cache1']
        raid_disk.create_partitions([Size(2, Unit.GibiByte)])
        raid_disk_1 = raid_disk.partitions[0]
        raid_disk2 = TestRun.disks['cache2']
        raid_disk2.create_partitions([Size(2, Unit.GibiByte)])
        raid_disk_2 = raid_disk2.partitions[0]

        config = RaidConfiguration(
            level=Level.Raid0,
            metadata=MetadataVariant.Legacy,
            number_of_devices=2,
            size=Size(1, Unit.GiB))

        raid_volume = Raid.create(config, [raid_disk_1, raid_disk_2])
        TestRun.LOGGER.info(f"RAID created successfully.")

        cache = casadm.start_cache(raid_volume, cache_mode, force=True)

    with TestRun.step("Add core device to cache, create filesystem and mount it."):
        core_disk1 = TestRun.disks['core1']
        core_disk1.create_partitions([Size(2, Unit.GibiByte)])
        core_dev1 = core_disk1.partitions[0]

        core1 = cache.add_core(core_dev1)
        core1.create_filesystem(Filesystem.ext3)
        core1.mount(mount_point)

    with TestRun.step("Add second core device to cache, create filesystem and mount it."):
        core_disk2 = TestRun.disks['core2']
        core_disk2.create_partitions([Size(2, Unit.GibiByte)])
        core_dev2 = core_disk2.partitions[0]

        core2 = cache.add_core(core_dev2)
        core2.create_filesystem(Filesystem.ext3)
        core2.mount(mount_point2)

    with TestRun.step("Create files with checksum on first core."):
        core1_md5sums = create_files_with_md5sums(mount_point, number_of_files)

    with TestRun.step("Create files with checksum on second core."):
        core2_md5sums = create_files_with_md5sums(mount_point2, number_of_files)

    with TestRun.step("Compare checksum on first core."):
        compare_md5sums(core1_md5sums, mount_point)

    with TestRun.step("Compare checksum on second core."):
        compare_md5sums(core2_md5sums, mount_point2)


def create_files_with_md5sums(destination_path, files_count):
    md5sums = list()
    for i in range(0, files_count):
        temp_file = f"/tmp/file{i}"
        destination_file = f"{destination_path}/file{i}"

        test_file = fs_utils.create_random_test_file(temp_file, test_file_size)
        test_file.copy(destination_file, force=True)

        md5sums.append(test_file.md5sum())

    TestRun.LOGGER.info(f"Files created and copied to core successfully.")
    return md5sums


def compare_md5sums(md5_sums_source, files_to_check_path):
    md5_sums_elements = len(md5_sums_source)

    for i in range(md5_sums_elements):
        file_to_check_path = f"{files_to_check_path}/file{i}"
        file_to_check = fs_utils.parse_ls_output(fs_utils.ls_item(file_to_check_path))[0]

        if md5_sums_source[i] != file_to_check.md5sum():
            TestRun.fail(f"Source and target files {file_to_check_path} checksums are different.")

    TestRun.LOGGER.info(f"Successful verification, md5sums match.")
