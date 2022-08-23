#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cache_config import CacheMode, CacheLineSize
from core.test_run import TestRun
from api.cas import cli, casadm
from api.cas.cli_messages import (
    check_stderr_msg,
    start_cache_on_already_used_dev,
    start_cache_with_existing_id
)
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
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


@pytest.mark.CI
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_data_integrity(cache_mode, cache_line_size, filesystem):
    """
    title: Check basic data integrity after stopping the cache
    pass criteria:
        - System does not crash.
        - All operations complete successfully.
        - Data consistency is preserved.
    """
    cache_id = core_id = 1
    mountpoint = "/mnt"
    filepath = f"{mountpoint}/file"

    with TestRun.step("Prepare partitions for cache (200MiB) and for core (100MiB)"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(100, Unit.MebiByte)])
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core device"):
        cache = casadm.start_cache(cache_part, cache_mode, cache_line_size, cache_id, True)
        core = cache.add_core(core_part, core_id)

    with TestRun.step("Create filesystem on CAS device and mount it"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(filepath)
            .count(1)
            .block_size(Size(50, Unit.MebiByte))
            .run()
        )
        test_file = File(filepath)
        md5_before = test_file.md5sum()

    with TestRun.step("Unmount and stop the cache"):
        core.unmount()
        cache.flush_cache()
        cache.stop()

    with TestRun.step("Mount the core device and check for file"):
        core_part.mount(mountpoint)
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")
