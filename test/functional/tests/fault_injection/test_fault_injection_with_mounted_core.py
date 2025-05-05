#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser, cli, cli_messages
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.disk_tools import get_block_size, create_partitions
from test_tools.fs_tools import Filesystem, create_random_test_file, check_if_file_exists
from test_utils.filesystem.file import File
from test_utils.filesystem.symlink import Symlink
from type_def.size import Size, Unit

mount_point, mount_point2 = "/mnt/cas", "/mnt/cas2"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_cache_with_mounted_core():
    """
        title: Fault injection test for adding mounted core on cache load.
        description: |
          Negative test of the ability of CAS to add to cache while its loading
          core device which is mounted.
        pass_criteria:
          - No system crash while loading cache.
          - Adding mounted core while loading cache fails.
    """
    with TestRun.step("Prepare cache and core devices. Start CAS."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Add core device with xfs filesystem to cache and mount it."):
        core_part.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_part)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in mount point of exported object and check its md5 sum."):
        test_file = create_random_test_file(test_file_path)
        test_file_md5_before = test_file.md5sum()

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Mount core device."):
        core_part.mount(mount_point)

    with TestRun.step("Try to load cache."):
        cache = casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1 Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 0:
            TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")

    with TestRun.step("Check md5 sum of test file again."):
        if test_file_md5_before != test_file.md5sum():
            TestRun.LOGGER.error("Md5 sum of test file is different.")
        core_part.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
def test_stop_cache_with_mounted_partition():
    """
        title: Fault injection test for removing core and stopping cache with mounted core.
        description: |
          Negative test of the ability of CAS to remove core and stop cache while core
          is still mounted.
        pass_criteria:
          - No system crash.
          - Unable to stop cache when partition is mounted.
          - Unable to remove core when partition is mounted.
          - casadm displays proper message.
    """
    with TestRun.step("Prepare cache device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Prepare 2 core devices."):
        core_dev, core_dev2 = TestRun.disks['core'], TestRun.disks['core2']

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Add core devices to cache."):
        core = cache.add_core(core_dev)
        core2 = cache.add_core(core_dev2)

    with TestRun.step("Create partitions on one exported object."):
        core.block_size = Unit(get_block_size(core.get_device_id()))
        create_partitions(core, 2 * [Size(4, Unit.GibiByte)])
        fs_part = core.partitions[0]

    with TestRun.step("Create xfs filesystems on one exported object partition "
                      "and on the non-partitioned exported object."):
        fs_part.create_filesystem(Filesystem.xfs)
        core2.create_filesystem(Filesystem.xfs)

    with TestRun.step("Mount created filesystems."):
        fs_part.mount(mount_point)
        core2.mount(mount_point2)

    with TestRun.step("Ensure /etc/mtab exists."):
        if not check_if_file_exists("/etc/mtab"):
            Symlink.create_symlink("/proc/self/mounts", "/etc/mtab")

    with TestRun.step("Try to remove the core with partitions from cache."):
        output = TestRun.executor.run_expect_fail(cli.remove_core_cmd(cache_id=str(cache.cache_id),
                                                                      core_id=str(core.core_id)))
        messages = cli_messages.remove_mounted_core.copy()
        messages.append(fs_part.path)
        cli_messages.check_stderr_msg(output, messages)

    with TestRun.step("Try to remove the core without partitions from cache."):
        output = TestRun.executor.run_expect_fail(cli.remove_core_cmd(cache_id=str(cache.cache_id),
                                                                      core_id=str(core2.core_id)))
        messages = cli_messages.remove_mounted_core.copy()
        messages.append(core2.path)
        cli_messages.check_stderr_msg(output, messages)

    with TestRun.step("Try to stop CAS."):
        output = TestRun.executor.run_expect_fail(cli.stop_cmd(cache_id=str(cache.cache_id)))
        messages = cli_messages.stop_cache_mounted_core.copy()
        messages.append(fs_part.path)
        messages.append(core2.path)
        cli_messages.check_stderr_msg(output, messages)

    with TestRun.step("Unmount core devices."):
        fs_part.unmount()
        core2.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_cache_with_mounted_partition_no_mtab():
    """
        title: Test for removing core and stopping cache when casadm is unable to check mounts.
        description: |
          Negative test of the ability of CAS to remove core and stop cache while core
          is still mounted and casadm is unable to check mounts.
        pass_criteria:
          - No system crash.
          - Unable to stop cache when partition is mounted.
          - Unable to remove core when partition is mounted.
          - casadm displays proper message informing that mount check was performed by kernel module
    """
    with TestRun.step("Prepare cache and core devices. Start CAS."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(4, Unit.GibiByte)])
        core_part = core_dev.partitions[0]
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Add core device with xfs filesystem and mount it."):
        core_part.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_part)
        core.mount(mount_point)

    with TestRun.step("Move /etc/mtab"):
        if check_if_file_exists("/etc/mtab"):
            mtab = File("/etc/mtab")
        else:
            mtab = Symlink.create_symlink("/proc/self/mounts", "/etc/mtab")
        mtab.move("/tmp")

    with TestRun.step("Try to remove core from cache."):
        output = TestRun.executor.run_expect_fail(cli.remove_core_cmd(cache_id=str(cache.cache_id),
                                                                      core_id=str(core.core_id)))
        cli_messages.check_stderr_msg(output, cli_messages.remove_mounted_core_kernel)

    with TestRun.step("Try to stop CAS."):
        output = TestRun.executor.run_expect_fail(cli.stop_cmd(cache_id=str(cache.cache_id)))
        cli_messages.check_stderr_msg(output, cli_messages.stop_cache_mounted_core_kernel)

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Remove core."):
        core.remove_core()

    with TestRun.step("Re-add core."):
        cache.add_core(core_part)

    with TestRun.step("Stop cache."):
        cache.stop()

    mtab.move("/etc")
