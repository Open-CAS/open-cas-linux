#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.os_utils import drop_caches, DropCachesMode, sync
from test_utils.size import Size, Unit


mount_point = "/mnt/test"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("reboot_type", ["soft", "hard"])
@pytest.mark.require_plugin("power_control")
def test_load_after_clean_shutdown(reboot_type, cache_mode, filesystem):
    """
        title: Planned system shutdown test.
        description: Test for data consistency after clean system shutdown.
        pass_criteria:
          - DUT should reboot successfully.
          - Checksum of file on core device should be the same before and after reboot.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_dev = TestRun.disks['core']
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)
        core.create_filesystem(filesystem, blocksize=int(Size(1, Unit.Blocks4096)))
        core.mount(mount_point)

    with TestRun.step("Create file on cache and count its checksum."):
        test_file = File(os.path.join(mount_point, "test_file"))
        Dd()\
            .input("/dev/zero")\
            .output(test_file.full_path)\
            .block_size(Size(1, Unit.KibiByte))\
            .count(1024)\
            .run()
        test_file.refresh_item()
        test_file_md5 = test_file.md5sum()
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Reset platform."):
        if reboot_type == "soft":
            TestRun.executor.reboot()
        else:
            power_control = TestRun.plugin_manager.get_plugin('power_control')
            power_control.power_cycle()

    with TestRun.step("Load cache."):
        casadm.load_cache(cache_dev)
        core.mount(mount_point)

    with TestRun.step("Check file md5sum."):
        test_file.refresh_item()
        if test_file_md5 != test_file.md5sum():
            TestRun.LOGGER.error("Checksums does not match - file is corrupted.")
        else:
            TestRun.LOGGER.info("File checksum is correct.")

    with TestRun.step("Remove test file."):
        test_file.remove()
