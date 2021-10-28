#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, cli
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_plugin("power_control")
def test_fault_power_hit_init(cache_mode):
    """
        title: Test with power hit and verification of metadata initialization after it.
        description: |
          Test if there will be metadata initialization after wake up
          - when starting cache with initialization.
        pass_criteria:
          - Start cache with initialization works correctly after power hit.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)
        cache_device_link = cache_dev.get_device_link("/dev/disk/by-id")

    with TestRun.step("Hard reset."):
        power_control = TestRun.plugin_manager.get_plugin('power_control')
        power_control.power_cycle()

    with TestRun.step("Start cache with re-initialization."):
        cache_dev.path = cache_device_link.get_target()
        TestRun.executor.run_expect_success(cli.start_cmd(
            cache_dev=str(cache_dev.path),
            cache_mode=str(cache_mode.name.lower()),
            force=True,
            load=False))
        TestRun.LOGGER.info(f"Successful assembly cache device with initialization")
