#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.fs_tools import Filesystem
from test_utils.filesystem.file import File
from test_tools.os_tools import drop_caches, DropCachesMode, sync
from type_def.size import Size, Unit


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("reboot_type", ["soft", "hard"])
@pytest.mark.require_plugin("power_control")
def test_load_after_clean_shutdown(reboot_type, cache_mode, filesystem):
    """
    title: Planned system shutdown test.
    description: |
        Test for data consistency after clean system shutdown.
    pass_criteria:
      - DUT reboot successful.
      - Checksum of file on core device should be the same before and after reboot.
    """
    mount_point = "/mnt/test"

    with TestRun.step("Prepare cache and core devices"):
        cache_disk = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_disk.create_partitions([Size(1, Unit.GibiByte)])

        cache_dev = cache_disk.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create filesystem on the core device and mount it"):
        core.create_filesystem(filesystem, blocksize=int(Size(1, Unit.Blocks4096)))
        core.mount(mount_point)

    with TestRun.step("Create file on exported object"):
        test_file = File(posixpath.join(mount_point, "test_file"))

        dd = (
            Dd()
            .input("/dev/zero")
            .output(test_file.full_path)
            .block_size(Size(1, Unit.KibiByte))
            .count(1024)
        )
        dd.run()

    with TestRun.step("Calculate test file md5sums before reboot"):
        test_file.refresh_item()
        test_file_md5 = test_file.md5sum()
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Reset platform"):
        if reboot_type == "soft":
            TestRun.executor.reboot()
        else:
            power_control = TestRun.plugin_manager.get_plugin("power_control")
            power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Load cache and mount core"):
        casadm.load_cache(cache_dev)
        core.mount(mount_point)

    with TestRun.step("Compare test file md5sums"):
        test_file.refresh_item()
        if test_file_md5 != test_file.md5sum():
            TestRun.LOGGER.error("Checksums does not match - file is corrupted.")
        else:
            TestRun.LOGGER.info("File checksum is correct.")

    with TestRun.step("Remove test file"):
        test_file.remove()
