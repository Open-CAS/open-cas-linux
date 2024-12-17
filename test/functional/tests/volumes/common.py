#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas.init_config import InitConfig, opencas_conf_path
from core.test_run import TestRun
from test_tools.disk_tools import get_block_device_names_list
from test_tools.fs_tools import create_random_test_file, parse_ls_output, ls_item
from type_def.size import Size, Unit

test_file_size = Size(500, Unit.KiloByte)
lvm_filters = [
    "a/.*/", "r|/dev/sd*|", "r|/dev/hd*|", "r|/dev/xvd*|", "r/disk/", "r/block/",
    "r|/dev/nvme*|", "r|/dev/vd*|"
]


def create_files_with_md5sums(destination_path, files_count):
    md5sums = list()
    for i in range(0, files_count):
        temp_file = f"/tmp/file{i}"
        destination_file = f"{destination_path}/file{i}"

        test_file = create_random_test_file(temp_file, test_file_size)
        test_file.copy(destination_file, force=True)

        md5sums.append(test_file.md5sum())

    TestRun.LOGGER.info(f"Files created and copied to core successfully.")
    return md5sums


def compare_md5sums(md5_sums_source, files_to_check_path, copy_to_tmp=False):
    md5_sums_elements = len(md5_sums_source)

    for i in range(md5_sums_elements):
        file_to_check_path = f"{files_to_check_path}/file{i}"
        file_to_check = parse_ls_output(ls_item(file_to_check_path))[0]

        if copy_to_tmp:
            file_to_check_path = f"{files_to_check_path}/filetmp"
            file_to_check.copy(file_to_check_path, force=True)
            file_to_check = parse_ls_output(ls_item(file_to_check_path))[0]

        if md5_sums_source[i] != file_to_check.md5sum():
            TestRun.fail(f"Source and target files {file_to_check_path} checksums are different.")

    TestRun.LOGGER.info(f"Successful verification, md5sums match.")


def get_test_configuration():
    InitConfig.create_init_config_from_running_configuration()
    config_output = TestRun.executor.run(f"cat {opencas_conf_path}")
    devices = get_block_device_names_list(exclude_list=[7])  # 7 stands for loop device

    return config_output.stdout, devices
