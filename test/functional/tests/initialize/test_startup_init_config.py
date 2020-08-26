#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm
from api.cas.casadm_parser import get_caches, get_cores
from api.cas.cache_config import CacheMode
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.filesystem.file import File
from test_tools.disk_utils import Filesystem
from test_utils import fstab
from test_tools.dd import Dd
from test_utils.size import Unit, Size


mountpoint = "/mnt"
filepath = f"{mountpoint}/file"


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_cas_startup(cache_mode, filesystem):
    """
    title: Test for starting CAS on system startup.
    pass_criteria:
      - System does not crash.
      - CAS modules are loaded before partitions are mounted.
      - Cache is loaded before partitions are mounted.
      - Exported object is mounted after startup is complete.
    """
    with TestRun.step("Prepare partitions for cache (200MiB) and for core (400MiB)"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        core = cache.add_core(core_part)

    with TestRun.step("Create and mount filesystem"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(filepath)
            .count(16)
            .block_size(Size(1, Unit.MebiByte))
            .run()
        )
        test_file = File(filepath)
        md5_before = test_file.md5sum()

    with TestRun.step("Add mountpoint fstab and create intelcas.conf"):
        fstab.add_mountpoint(device=core,
                             mount_point=mountpoint,
                             fs_type=filesystem)
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot"):
        TestRun.executor.reboot()

    with TestRun.step("Check if cache is started"):
        caches = list(get_caches())
        if len(caches) != 1:
            TestRun.fail(f"Expected one cache, got {len(caches)}!")
        if caches[0].cache_id != cache.cache_id:
            TestRun.fail("Invalid cache id!")

    with TestRun.step("Check if core is added"):
        cores = list(get_cores(cache.cache_id))
        if len(cores) != 1:
            TestRun.fail(f"Expected one core, got {len(cores)}!")
        if cores[0].core_id != core.core_id:
            TestRun.fail("Invalid core id!")

    with TestRun.step("Check if filesystem is mounted"):
        if not core.is_mounted():
            TestRun.fail("Core is not mounted!")

    with TestRun.step("Check if md5 checksum matches"):
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")

    with TestRun.step("Test cleanup"):
        fstab.remove_mountpoint(device=core)
        core.unmount()
        InitConfig.create_default_init_config()
        casadm.stop_all_caches()
