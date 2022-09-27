#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.cli import casadm_bin
from api.cas.cli_messages import check_stderr_msg, stop_cache_errors
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType, Disk
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem, unmount, mount
from test_tools.fs_utils import check_if_file_exists
from test_utils.filesystem.file import File
from test_utils.os_utils import sync
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_recover_cache_verify_core():
    """
        title: Recovery after turning off/on devices
        description: |
            Test data integrity after turning off cache device.
        pass_criteria:
          - Cache devices successfully loaded with metadata after turning devices off/on
          - md5sums before and after all operations match each other
          - creation, mount, unmount of filesystems on the core device succeeds
    """
    filesystems = [Filesystem.xfs, Filesystem.ext3, Filesystem.ext4]
    cache_cnt = len(filesystems)

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)] * cache_cnt)
        cache_devs = cache_disk.partitions
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(4, Unit.GibiByte)] * cache_cnt)
        core_devs = core_disk.partitions

    with TestRun.step("Start caches and add cores."):
        caches, cores = [], []
        for (cache_dev, core_dev) in zip(cache_devs, core_devs):
            cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
            core = cache.add_core(core_dev)
            caches.append(cache)
            cores.append(core)

    with TestRun.step("Create filesystem on core devices."):
        for (core, filesystem) in zip(cores, filesystems):
            core.create_filesystem(filesystem)

    with TestRun.step("Mount cache devices."):
        for (cache, core) in zip(caches, cores):
            core_mnt_point = f"{mount_point}-{cache.cache_id}-{core.core_id}"
            core.mount(core_mnt_point)

            with TestRun.step("Run IO"):
                dd = (
                    Dd()
                    .input("/dev/urandom")
                    .output(f"{core_mnt_point}/test")
                    .count(1)
                    .block_size(Size(50, Unit.MegaByte))
                )
                dd.run()

    with TestRun.step("Calculate cache md5sums before unplug."):
        core_mnt_md5s_before = [File(f"{core.mount_point}/test").md5sum() for core in cores]

    with TestRun.step("Umount core devices."):
        for core in cores:
            core.unmount()

    with TestRun.step("Dirty stop"):
        dirty_stop(cache_disk, caches)

    with TestRun.step("Start caches with load metadata and later stop them."):
        for cache_dev in cache_devs:
            cache = casadm.load_cache(cache_dev)
            cache.stop()

    with TestRun.step("Mount core devices."):
        for core, cache in zip(cores, caches):
            core_mnt_point = f"{mount_point}-{cache.cache_id}-{core.core_id}"
            mount(core.core_device, core_mnt_point)
            core.mount_point = core_mnt_point
            if not check_if_file_exists(f"{core_mnt_point}/test"):
                TestRun.LOGGER.error(f"Mounting core device {core_mnt_point} failed.")

    with TestRun.step("Calculate cache md5sums after recovery."):
        core_mnt_md5s_after = [File(f"{core.mount_point}/test").md5sum() for core in cores]

    with TestRun.step("Compare md5 sums for cores and core devices"):
        if core_mnt_md5s_before != core_mnt_md5s_after:
            TestRun.fail(
                f"MD5 sums of core before and after does not match."
                f"Expected: {core_mnt_md5s_before}, Actual: {core_mnt_md5s_after}"
            )

    with TestRun.step("Umount core devices."):
        for core_dev in core_devs:
            unmount(core_dev)


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_recover_cache_verify_exp_obj():
    """
        title: Recovery after turning off/on devices
        description: |
            Test data integrity after turning off cache device.
        pass_criteria:
          - Cache devices successfully loaded with metadata after turning devices off/on
          - md5sums before and after all operations match each other
          - creation, mount, unmount of filesystems succeeds on core exported object
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)] * 3)
        cache_devs = cache_disk.partitions
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(4, Unit.GibiByte)] * 3)
        core_devs = core_disk.partitions

    with TestRun.step("Start caches and add cores."):
        caches, cores = [], []
        for (cache_dev, core_dev) in zip(cache_devs, core_devs):
            cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
            core = cache.add_core(core_dev)
            caches.append(cache)
            cores.append(core)

    with TestRun.step("Create filesystem on core devices."):
        filesystems = [Filesystem.xfs, Filesystem.ext3, Filesystem.ext4]
        for (core, filesystem) in zip(cores, filesystems):
            core.create_filesystem(filesystem)

    with TestRun.step("Mount cache devices."):
        for (cache, core) in zip(caches, cores):
            core_mnt_point = f"{mount_point}-{cache.cache_id}-{core.core_id}"
            core.mount(core_mnt_point)

            with TestRun.step("Run IO"):
                dd = (
                    Dd()
                    .input("/dev/urandom")
                    .output(f"{core_mnt_point}/test")
                    .count(1)
                    .block_size(Size(50, Unit.MegaByte))
                )
                dd.run()
                sync()

    with TestRun.step("Calculate cache md5sums before unplug."):
        core_mnt_md5s_before = [File(f"{core.mount_point}/test").md5sum() for core in cores]

    with TestRun.step("Umount core devices."):
        for core in cores:
            core.unmount()

    with TestRun.step("Dirty stop"):
        dirty_stop(cache_disk, caches)

    with TestRun.step("Load caches with metadata."):
        for cache_dev in cache_devs:
            casadm.load_cache(cache_dev)

    with TestRun.step("Mount core devices."):
        for core, cache in zip(cores, caches):
            core_mnt_point = f"{mount_point}-{cache.cache_id}-{core.core_id}"
            core.mount(core_mnt_point)
            if not check_if_file_exists(f"{core_mnt_point}/test"):
                TestRun.LOGGER.error(f"Mounting core device {core_mnt_point} failed.")

    with TestRun.step("Calculate cache md5sums after recovery."):
        core_mnt_md5s_after = [File(f"{core.mount_point}/test").md5sum() for core in cores]

    with TestRun.step("Compare md5 sums for cores and core devices"):
        if core_mnt_md5s_before != core_mnt_md5s_after:
            TestRun.fail(
                f"MD5 sums of core before and after does not match."
                f"Expected: {core_mnt_md5s_before}, Actual: {core_mnt_md5s_after}"
            )

    with TestRun.step("Umount core devices."):
        for core in cores:
            core.unmount()


def dirty_stop(cache_disk, caches: list):
    with TestRun.step("Turn off cache devices."):
        cache_disk.unplug()

    with TestRun.step("Stop caches without flushing."):
        for cache in caches:
            cmd = f"{casadm_bin} --stop-cache --cache-id {cache.cache_id} --no-data-flush"
            output = TestRun.executor.run(cmd)
            if not check_stderr_msg(output, stop_cache_errors):
                TestRun.fail(f"Cache {cache.cache_id} stopping should fail.")

    with TestRun.step("Turn on devices."):
        Disk.plug_all_disks()
