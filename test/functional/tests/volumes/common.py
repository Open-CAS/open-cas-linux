#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from test_tools import fs_utils
from core.test_run import TestRun
from test_utils.size import Size, Unit

test_file_size = Size(500, Unit.KiloByte)


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


def compare_md5sums(md5_sums_source, files_to_check_path, copy_to_tmp=False):
    md5_sums_elements = len(md5_sums_source)

    for i in range(md5_sums_elements):
        file_to_check_path = f"{files_to_check_path}/file{i}"
        file_to_check = fs_utils.parse_ls_output(fs_utils.ls_item(file_to_check_path))[0]

        if copy_to_tmp:
            file_to_check_path = f"{files_to_check_path}/filetmp"
            file_to_check.copy(file_to_check_path, force=True)
            file_to_check = fs_utils.parse_ls_output(fs_utils.ls_item(file_to_check_path))[0]

        if md5_sums_source[i] != file_to_check.md5sum():
            TestRun.fail(f"Source and target files {file_to_check_path} checksums are different.")

    TestRun.LOGGER.info(f"Successful verification, md5sums match.")
