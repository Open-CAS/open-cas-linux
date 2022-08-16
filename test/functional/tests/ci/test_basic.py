#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from core.test_run import TestRun


def test_cas_version():
    """
    title: Check if CAS is installed
    description:
      Check if CAS is installed with --version flag and later
      checks if components version is consistent with version file
    pass criteria:
     - casadm command succeeds
     - Versions are matched from cmd and file in /var/lib/opencas/cas_version
    """
    cmd = f"casadm --version -o csv"
    output = TestRun.executor.run_expect_success(cmd).stdout
    cmd_cas_versions = output.split("\n")[1:]

    version_file_path = r"/var/lib/opencas/cas_version"
    file_read_cmd = f"cat {version_file_path} | grep CAS_VERSION="
    file_cas_version_str = TestRun.executor.run_expect_success(file_read_cmd).stdout
    file_cas_version = file_cas_version_str.split('=')[1]

    for version in cmd_cas_versions:
        splitted_version = version.split(",")
        if splitted_version[1] != file_cas_version:
            TestRun.LOGGER.error(f"""Version of {splitted_version[0]} from cmd doesn't match
             with file. Expected: {file_cas_version} Actual: {splitted_version[1]}""")
