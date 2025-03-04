#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cli import standby_activate_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.filesystem.symlink import Symlink
from type_def.size import Size, Unit
from api.cas.cache_config import CacheLineSize
from api.cas.cache import CacheStatus
from test_tools.dd import Dd
from test_tools.fs_tools import check_if_symlink_exists
from test_tools.os_tools import sync


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_standby_activate_different_cache_path(cache_line_size):
    """
    title: test_standby_activate_different_cache_path
    description: |
        Symlink-activated CAS partitions distinction test.
    pass_criteria:
      - Cache is successfully activated with symlink on second partition.
      - Cache is present and running.
    """
    with TestRun.step("Prepare two partitions with the same size."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(500, Unit.MebiByte)] * 2)
        active_cache_dev = cache_dev.partitions[0]
        standby_cache_dev = cache_dev.partitions[1]
        cache_id = 1

    with TestRun.step("Start a regular cache instance on one of the partitions and stop it."):
        active_cache = casadm.start_cache(
            active_cache_dev, cache_line_size=cache_line_size, force=True
        )
        active_cache.stop()

    with TestRun.step("Create a symbolic link to the second partition."):
        link_path = "/dev/disk/by-id/standby_cache_dev_link"
        symlink = Symlink.create_symlink(link_path, standby_cache_dev.path, True)

        if not check_if_symlink_exists(link_path):
            TestRun.fail("Failed to create a symlink.")
        TestRun.LOGGER.info("Symlink was created successfully.")

    with TestRun.step("Start a standby instance on the second partition using original path."):
        standby_cache = casadm.standby_init(standby_cache_dev, cache_id, cache_line_size, True)

    with TestRun.step(
        "Populate the standby cache with valid CAS metadata from the first partition."
    ):
        Dd().input(active_cache_dev.path).output(f"/dev/cas-cache-{cache_id}").run()
        sync()

    with TestRun.step("Detach standby cache."):
        standby_cache.standby_detach()

    with TestRun.step("Activate cache providing symlink."):
        output = TestRun.executor.run(
            standby_activate_cmd(symlink.get_symlink_path(), str(cache_id), False)
        )
        if output.exit_code != 0:
            TestRun.LOGGER.error("Failed to activate standby cache.")

    with TestRun.step(
        "Verify that the activation succeeded, and the regular cache instance is running."
    ):
        if standby_cache.get_status() != CacheStatus.running:
            TestRun.LOGGER.error("Cache is not running.")

        standby_cache.stop()
        symlink.remove_symlink()

        if check_if_symlink_exists(symlink.get_symlink_path()):
            TestRun.LOGGER.error("Failed to remove symlink.")
