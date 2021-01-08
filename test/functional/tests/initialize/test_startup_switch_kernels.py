#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
#
# These tests require GRUB as boot loader and manager. Make sure your GRUB configuration files
# have been generated with GRUB_DEFAULT=saved in /etc/default/grub. Otherwise these tests won't
# work.

import pytest

from api.cas import casadm
from api.cas.casadm_parser import get_caches, get_cores
from api.cas.init_config import InitConfig
from test_utils.os_utils import switch_kernel, get_current_kernel_version
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils import fstab
from test_utils.size import Unit, Size

mountpoint = "/mnt"
filepath = f"{mountpoint}/file"


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_compatible_kernel
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cas_startup_compatible_kernel():
    """
    title: Test for starting CAS on system startup after reboot to compatible kernel.
    pass_criteria:
      - System does not crash.
      - CAS modules are loaded before partitions are mounted.
      - Cache is loaded before partitions are mounted.
      - Exported object is mounted after startup is complete.
    """
    with TestRun.step("Prepare partitions for cache and for core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Create filesystem, add core and mount it."):
        core_part.create_filesystem(Filesystem.ext4)
        core = cache.add_core(core_part)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum."):
        test_file = fs_utils.create_random_test_file(filepath, Size(16, Unit.MebiByte))
        md5_before = test_file.md5sum()

    with TestRun.step("Add mountpoint to fstab and create opencas.conf."):
        fstab.add_mountpoint(device=core,
                             mount_point=mountpoint,
                             fs_type=Filesystem.ext4)
        InitConfig.create_init_config_from_running_configuration(
            "lazy_startup=true", "lazy_startup=true")

    with TestRun.step("Change kernel subversion."):
        previous_kernel = get_current_kernel_version()
        TestRun.LOGGER.info(f"Current kernel version: {previous_kernel}")
        switch_kernel()

    with TestRun.step("Reboot and check kernel version."):
        TestRun.executor.reboot()
        temporary_kernel = get_current_kernel_version()
        if temporary_kernel == previous_kernel:
            fstab.remove_mountpoint(device=core)
            core.unmount()
            TestRun.fail("Kernel version has not changed!")

        TestRun.LOGGER.info(f"Temporary kernel version: {temporary_kernel}")

    with TestRun.step("Check if cache is started."):
        caches = list(get_caches())
        if len(caches) != 1:
            TestRun.LOGGER.error(f"Expected one cache, got {len(caches)}!")
        if caches[0].cache_id != cache.cache_id:
            TestRun.LOGGER.error("Invalid cache id!")

    with TestRun.step("Check if core is added."):
        cores = list(get_cores(cache.cache_id))
        if len(cores) != 1:
            TestRun.LOGGER.error(f"Expected one core, got {len(cores)}!")
        if cores[0].core_id != core.core_id:
            TestRun.LOGGER.error("Invalid core id!")

    with TestRun.step("Check if core is mounted."):
        if not core.is_mounted():
            TestRun.LOGGER.error("Core is not mounted!")

    with TestRun.step("Check if md5 checksum matches."):
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.LOGGER.error("Md5 checksum mismatch!")

    with TestRun.step("Test cleanup."):
        fstab.remove_mountpoint(device=core)
        core.unmount()
        InitConfig.create_default_init_config()
        casadm.stop_all_caches()

    with TestRun.step("Reboot and check kernel version."):
        TestRun.executor.reboot()
        current_kernel = get_current_kernel_version()
        if current_kernel != previous_kernel:
            TestRun.fail("Kernel version has not changed back!")

        TestRun.LOGGER.info(f"Current kernel version: {current_kernel}")

