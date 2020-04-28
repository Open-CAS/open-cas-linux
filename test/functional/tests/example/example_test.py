#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_utils.filesystem.file import File
from test_utils.filesystem.directory import Directory
from test_tools import fs_utils


def setup_module():
    TestRun.LOGGER.warning("Entering setup method")


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
        with TestRun.step("Genetare partitions table"):
            part_sizes = []
            for i in range(1, 6):
                part_sizes.append(Size(10 * i + 100, Unit.MebiByte))
        with TestRun.step("Create partitions"):
            test_disk.create_partitions(part_sizes)
        for i in TestRun.iteration(range(0, 5)):
            with TestRun.step(f"Create filesystem on partition {i}"):
                test_disk.partitions[i].create_filesystem(Filesystem.ext3)



def test_create_example_files():
    """
        title: Example test manipulating on filesystem.
        description: Perform various operaations on filesystem.
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

