#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from core.test_run import TestRun
from api.cas import cli
from api.cas.cli_messages import (
    check_stderr_msg,
    start_cache_on_already_used_dev,
    start_cache_with_existing_id
)
from storage_devices.disk import DiskType, DiskTypeSet
from test_utils.size import Size, Unit


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

@pytest.mark.CI
@pytest.mark.require_disk("cache_1", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_negative_start_cache():
    """
    title: Test start cache negative on cache device
    description:
      Check for negative cache start scenarios
    pass criteria:
      - Cache start succeeds
      - Fails to start cache on the same device with another id
      - Fails to start cache on another partition with the same id
    """
    with TestRun.step("Set up device"):
        cache_dev = TestRun.disks["cache_1"]
        cache_dev.create_partitions([Size(2000, Unit.MebiByte)] * 2)
        cache_dev_1 = cache_dev.partitions[0]
        cache_dev_2 = cache_dev.partitions[1]

    with TestRun.step("Start cache on cache device"):
        TestRun.executor.run_expect_success(
            cli.start_cmd(cache_dev_1.path, cache_id="1", force=True)
        )

    with TestRun.step("Start cache on the same device but with another ID"):
        output = TestRun.executor.run_expect_fail(
            cli.start_cmd(cache_dev_1.path, cache_id="2", force=True)
        )
        if not check_stderr_msg(output, start_cache_on_already_used_dev):
            TestRun.fail(f"Received unexpected error message: {output.stderr}")

    with TestRun.step("Start cache with the same ID on another cache device"):
        output = TestRun.executor.run_expect_fail(
            cli.start_cmd(cache_dev_2.path, cache_id="1", force=True)
        )
        if not check_stderr_msg(output, start_cache_with_existing_id):
            TestRun.fail(f"Received unexpected error message: {output.stderr}")
