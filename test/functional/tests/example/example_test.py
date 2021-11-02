#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.directory import Directory
from test_utils.filesystem.file import File
from test_utils.size import Size, Unit


def setup_module():
    """
    Function called by python
    """
    TestRun.LOGGER.info("Entering setup method")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_create_example_partitions():
    """
        title: Example test creating partitions and filesystems.
        description: Create 6 partitions and create filesystem on each of them.
        pass_criteria:
          - Partitions are created with no error.
          - Filesystems are created successfully.
    """
    with TestRun.step("Prepare"):
        test_disk = TestRun.disks['cache']

    with TestRun.group("Repartition disk"):
        with TestRun.step("Generate partitions table"):
            part_sizes = []
            for i in range(1, 6):
                part_sizes.append(Size(10 * i + 100, Unit.MebiByte))
        with TestRun.step("Create partitions"):
            test_disk.create_partitions(part_sizes)
        for i in TestRun.iteration(range(0, 5)):
            with TestRun.step(f"Create filesystem on partition {i}"):
                test_disk.partitions[i].create_filesystem(Filesystem.ext3)


@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_raid_example():
    """
        title: Example test using RAID API.
        description: Create and discover RAID volumes.
        pass_criteria:
          - RAID created.
          - RAID discovered.
    """
    with TestRun.step("Prepare"):
        test_disk_1 = TestRun.disks['cache1']
        test_disk_2 = TestRun.disks['cache2']

    with TestRun.step("Create RAID"):
        config = RaidConfiguration(
            level=Level.Raid1,
            metadata=MetadataVariant.Imsm,
            number_of_devices=2,
            size=Size(20, Unit.GiB)
        )
        raid = Raid.create(config, [test_disk_1, test_disk_2])

    with TestRun.group("Discover RAIDs"):
        raids = Raid.discover()

    with TestRun.group("Check if created RAID was discovered"):
        if raid not in raids:
            TestRun.LOGGER.error("Created RAID not discovered in system!")


def test_create_example_files():
    """
        title: Example test manipulating on filesystem.
        description: Perform various operations on filesystem.
        pass_criteria:
          - System does not crash.
          - All operations complete successfully.
          - Data consistency is being preserved.
    """
    with TestRun.step("Create file with content"):
        file1 = File.create_file("example_file")
        file1.write("Test file\ncontent line\ncontent")
    with TestRun.step("Read file content"):
        content_before_change = file1.read()
        TestRun.LOGGER.info(f"File content: {content_before_change}")
    with TestRun.step("Replace single line in file"):
        fs_utils.replace_in_lines(file1, 'content line', 'replaced line')
    with TestRun.step("Read file content and check if it changed"):
        content_after_change = file1.read()
        if content_before_change == content_after_change:
            TestRun.fail("Content didn't changed as expected")

    with TestRun.step("Make copy of the file and check if md5 sum matches"):
        file2 = file1.copy('/tmp', force=True)
        if file1.md5sum() != file2.md5sum():
            TestRun.fail("md5 sum doesn't match!")
    with TestRun.step("Change permissions of second file"):
        file2.chmod_numerical(123)
    with TestRun.step("Remove second file"):
        fs_utils.remove(file2.full_path, True)

    with TestRun.step("List contents of home directory"):
        dir1 = Directory("~")
        dir_content = dir1.ls()
    with TestRun.step("Change permissions of file"):
        file1.chmod(fs_utils.Permissions['r'] | fs_utils.Permissions['w'],
                    fs_utils.PermissionsUsers(7))
    with TestRun.step("Log home directory content"):
        for item in dir_content:
            TestRun.LOGGER.info(f"Item {str(item)} - {type(item).__name__}")
    with TestRun.step("Remove file"):
        fs_utils.remove(file1.full_path, True)
