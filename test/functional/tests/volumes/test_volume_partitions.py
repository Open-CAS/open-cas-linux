#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from storage_devices.partition import Partition
from test_tools import fs_utils, disk_utils
from test_tools.disk_utils import PartitionTable, Filesystem
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
cores_number = 16


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("partition_table", PartitionTable)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cas_preserves_partitions(partition_table, filesystem, cache_mode):
    """
        title: Volume test for preserving partition table from core device.
        description: |
          Validation of the ability of CAS to preserve partition table on core device
          after adding it to cache.
        pass_criteria:
          - Md5 sums on partitions shall be identical before and after running cache.
          - Partition table shall be preserved on exported object.
    """
    with TestRun.step(f"Prepare cache and core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_sizes = [Size(1, Unit.GibiByte)] * cores_number
        core_dev.create_partitions(core_sizes, partition_table)

    with TestRun.step("Create filesystem on core devices."):
        for i in range(cores_number):
            core_dev.partitions[i].create_filesystem(filesystem)

    with TestRun.step("Mount core devices and create test files."):
        files = []
        for i, core in enumerate(core_dev.partitions):
            mount_path = f"{mount_point}{i}"
            core.mount(mount_path)
            test_file_path = f"{mount_path}/test_file"
            files.append(fs_utils.create_random_test_file(test_file_path))

    with TestRun.step("Check md5 sums of test files."):
        test_files_md5sums = []
        for file in files:
            test_files_md5sums.append(file.md5sum())

    with TestRun.step("Unmount core devices."):
        for core in core_dev.partitions:
            core.unmount()

    with TestRun.step(f"Start cache."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

    with TestRun.step("Add cores to cache."):
        cores = []
        for i in range(cores_number):
            cores.append(cache.add_core(core_dev.partitions[i]))

    with TestRun.step("Mount core devices."):
        for i, core in enumerate(cores):
            mount_path = f"{mount_point}{i}"
            core.mount(mount_path)

    with TestRun.step("Check again md5 sums of test files."):
        test_files_md5sums_new = []
        for file in files:
            test_files_md5sums_new.append(file.md5sum())

    with TestRun.step("Unmount core devices."):
        for core in cores:
            core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Compare md5 sums of test files."):
        if test_files_md5sums != test_files_md5sums_new:
            TestRun.fail("Md5 sums are different.")


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("partition_table", PartitionTable)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_partition_create_cas(partition_table, filesystem, cache_mode):
    """
        title: Test for preserving partition table created on exported volume after stopping cache.
        description: |
          Validation of the ability of CAS to preserve partition table created on exported volume
          after stopping cache.
        pass_criteria:
          - Md5 sums on partitions shall be identical before and after stopping cache.
          - Partition table shall be preserved on core device.
    """
    with TestRun.step(f"Prepare cache and core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(256, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']

    with TestRun.step(f"Start cache."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create partitions on exported device."):
        core_sizes = [Size(1, Unit.GibiByte)] * cores_number
        core.block_size = core_dev.block_size
        disk_utils.create_partitions(core, core_sizes, partition_table)

    with TestRun.step("Create filesystem on core devices."):
        for part in core.partitions:
            part.create_filesystem(filesystem)

    with TestRun.step("Mount core devices and create test files."):
        files = []
        for i, part in enumerate(core.partitions):
            mount_path = f"{mount_point}{i}"
            part.mount(mount_path)
            test_file_path = f"{mount_path}/test_file"
            files.append(fs_utils.create_random_test_file(test_file_path))

    with TestRun.step("Check md5 sums of test files."):
        test_files_md5sums = []
        for file in files:
            test_files_md5sums.append(file.md5sum())

    with TestRun.step("Unmount core devices."):
        for part in core.partitions:
            part.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Read partitions on core device."):
        for part in core.partitions:
            part.parent_device = core_dev
            new_part = Partition(part.parent_device, part.type, part.number)
            core_dev.partitions.append(new_part)

    with TestRun.step("Mount core devices."):
        counter = 1
        for i, core in enumerate(core_dev.partitions):
            mount_path = f"{mount_point}{i}"
            core.mount(mount_path)
            counter += 1

    with TestRun.step("Check again md5 sums of test files."):
        test_files_md5sums_new = []
        for file in files:
            test_files_md5sums_new.append(file.md5sum())

    with TestRun.step("Unmount core devices."):
        for core in core_dev.partitions:
            core.unmount()

    with TestRun.step("Compare md5 sums of test files."):
        if test_files_md5sums != test_files_md5sums_new:
            TestRun.fail("Md5 sums are different.")
