#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode, CleaningPolicy
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_plugin("power_control")
def test_dirty_load():
    """
        title: Loading cache after dirty shutdown.
        description: Test for loading cache containing dirty data after DUT hard restart.
        pass_criteria:
          - DUT should reboot successfully.
          - Cache should load successfully.
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(2, Unit.GibiByte)] * 2)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache in Write-Back mode and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB)
        cores = []
        for dev in core_devices:
            cores.append(cache.add_core(dev))

    with TestRun.step("Set cleaning policy to nop."):
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Populate cache with dirty data."):
        fio = Fio().create_command()\
            .size(Size(1, Unit.GibiByte))\
            .read_write(ReadWrite.randwrite)\
            .io_engine(IoEngine.libaio)\
            .block_size(Size(1, Unit.Blocks4096))
        for i, core in enumerate(cores):
            fio.add_job(f"core{i}").target(core.path)
        fio.run()

        if cache.get_dirty_blocks() <= Size.zero():
            TestRun.fail("Cache does not contain dirty data.")

    with TestRun.step("Remove one core without flushing dirty data."):
        casadm.remove_core_with_script_command(cache.cache_id, core.core_id, True)

    with TestRun.step("Reset platform."):
        power_control = TestRun.plugin_manager.get_plugin('power_control')
        power_control.power_cycle()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

        caches_num = len(casadm_parser.get_caches())
        if caches_num != 1:
            TestRun.LOGGER.error(f"Wrong number of caches. Expected 1, actual {caches_num}.")

        cores_num = len(casadm_parser.get_cores(cache.cache_id))
        if cores_num != 1:
            TestRun.LOGGER.error(f"Wrong number of cores. Expected 1, actual {cores_num}.")
