#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.casadm_params import OutputFormat
from api.cas.cli import start_cmd
from core.test_run import TestRun
from api.cas import casadm
from api.cas.cli_messages import (
    check_stderr_msg,
    start_cache_on_already_used_dev,
    start_cache_with_existing_id,
)
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.output import CmdException
from test_utils.size import Size, Unit

version_file_path = r"/var/lib/opencas/cas_version"
mountpoint = "/mnt"


@pytest.mark.CI
def test_cas_version():
    """
    title: Test for CAS version
    description:
        Check if CAS print version cmd returns consistent version with version file
    pass criteria:
      - casadm version command succeeds
      - versions from cmd and file in /var/lib/opencas/cas_version are consistent
    """

    with TestRun.step("Read cas version using casadm cmd"):
        output = casadm.print_version(output_format=OutputFormat.csv)
        cmd_version = output.stdout
        cmd_cas_versions = [version.split(",")[1] for version in cmd_version.split("\n")[1:]]

    with TestRun.step(f"Read cas version from {version_file_path} location"):
        file_read = fs_utils.read_file(version_file_path).split("\n")
        file_cas_version = next(
            (line.split("=")[1] for line in file_read if "CAS_VERSION=" in line)
        )

    with TestRun.step("Compare cmd and file versions"):
        if not all(file_cas_version == cmd_cas_version for cmd_cas_version in cmd_cas_versions):
            TestRun.LOGGER.error(f"Cmd and file versions doesn`t match")


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
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

    with TestRun.step("Prepare cache device"):
        cache_dev = TestRun.disks["cache"]

        cache_dev.create_partitions([Size(2, Unit.GibiByte)] * 2)

        cache_dev_1 = cache_dev.partitions[0]
        cache_dev_2 = cache_dev.partitions[1]

    with TestRun.step("Start cache on cache device"):
        casadm.start_cache(cache_dev=cache_dev_1, force=True)

    with TestRun.step("Start cache on the same device but with another ID"):
        try:
            output = TestRun.executor.run(
                start_cmd(
                    cache_dev=cache_dev_1.path,
                    cache_id="2",
                    force=True,
                )
            )
            TestRun.fail("Two caches started on same device")
        except CmdException:
            if not check_stderr_msg(output, start_cache_on_already_used_dev):
                TestRun.fail(f"Received unexpected error message: {output.stderr}")

    with TestRun.step("Start cache with the same ID on another cache device"):
        try:
            output = TestRun.executor.run(
                start_cmd(
                    cache_dev=cache_dev_2.path,
                    cache_id="1",
                    force=True,
                )
            )
            TestRun.fail("Two caches started with same ID")
        except CmdException:
            if not check_stderr_msg(output, start_cache_with_existing_id):
                TestRun.fail(f"Received unexpected error message: {output.stderr}")


@pytest.mark.CI
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_data_integrity(filesystem, cache_mode, cache_line_size):
    """
    title: Basic data integrity test
    description:
        Check basic data integrity after stopping the cache
    pass criteria:
      - System does not crash.
      - All operations complete successfully.
      - Data consistency is preserved.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(200, Unit.MebiByte)])
        core_device.create_partitions([Size(100, Unit.MebiByte)])

        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core device"):
        cache = casadm.start_cache(
            cache_dev=cache_part, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True
        )
        core = cache.add_core(core_dev=core_part)

    with TestRun.step("Create filesystem on CAS device and mount it"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(f"{mountpoint}/test_file")
            .count(1)
            .block_size(Size(50, Unit.MebiByte))
            .run()
        )
        test_file = File(f"{mountpoint}/test_file")
        md5_before = test_file.md5sum()

    with TestRun.step("Unmount core"):
        core.unmount()

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Mount the core device and check for file"):
        core_part.mount(mountpoint)
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")
