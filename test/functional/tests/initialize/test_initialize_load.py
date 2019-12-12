#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import *
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import *
from test_utils.size import Size, Unit


@pytest.mark.parametrize("core_number", [1, 4])
@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_four_to_one_without_params(cache_mode, cleaning_policy, core_number):
    """
        title: Initialize test for loading CAS with 1 cache and 4 cores.
        description: |
          Verify that loading cache configurations works properly in every mode
          with 1 cache and 4 cores. Use minimal number of possible parameters with load command.
        pass_criteria:
          - All test steps complete without errors.
          - No data corruption is found.
    """
    with TestRun.step(f"Prepare 1 cache and {core_number} core devices"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_devices = []
        core_size = []
        for i in range(0, core_number):
            core_size.append(Size(4, Unit.GibiByte))
        core_dev.create_partitions(core_size)
        for i in range(0, core_number):
            core_devices.append(core_dev.partitions[i])

    with TestRun.step(f"Start cache with {core_number} cores."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = []
        for i in range(0, core_number):
            core.append(cache.add_core(core_devices[i]))
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != core_number:
            TestRun.fail(f"Expected cores count: {core_number}; Actual cores count: {cores_count}.")

    with TestRun.step("Configure optional parameters."):
        cache.set_cleaning_policy(cleaning_policy)
        if cleaning_policy == CleaningPolicy.alru:
            alru = FlushParametersAlru()
            alru.activity_threshold = Time(milliseconds=1000)
            alru.flush_max_buffers = 10
            alru.staleness_time = Time(seconds=60)
            alru.wake_up_time = Time(seconds=5)
            cache.set_params_alru(alru)
        if cleaning_policy == CleaningPolicy.acp:
            acp = FlushParametersAcp()
            acp.flush_max_buffers = 100
            acp.wake_up_time = Time(seconds=5)
            cache.set_params_acp(acp)

    with TestRun.step("Run FIO on cache's exported object"):
        for i in range(0, core_number):
            Fio().create_command() \
                .io_engine(IoEngine.libaio) \
                .io_depth(64) \
                .size(Size(4, Unit.GibiByte)) \
                .read_write(ReadWrite.randrw) \
                .block_size(Size(64, Unit.MebiByte)) \
                .target(f"{core[i].system_path}") \
                .run()

    with TestRun.step("Stop CAS."):
        cache.stop()
        if len(casadm_parser.get_caches()) != 0:
            TestRun.fail("There are still running caches after stopping service.")
        if len(casadm_parser.get_cores(cache.cache_id)) != 0:
            TestRun.fail("There are still running cores after stopping service.")

    with TestRun.step("Load CAS."):
        casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != core_number:
            TestRun.fail(f"Expected cores count: {core_number}; Actual cores count: {cores_count}.")

    with TestRun.step("Compare cache configuration before and after load."):
        if cache_mode != cache.get_cache_mode():
            TestRun.LOGGER.fail("Cache mode are different.")
        if cleaning_policy != cache.get_cleaning_policy():
            TestRun.LOGGER.fail("Cleaning policy are different.")
            if cleaning_policy == CleaningPolicy.alru:
                cache.get_flush_parameters_alru()
                TestRun.LOGGER.fail("Cleaning policy parameters are different.")
            if cleaning_policy == CleaningPolicy.acp:
                cache.get_flush_parameters_acp()
                TestRun.LOGGER.fail("Cleaning policy parameters are different.")

    with TestRun.step("Run FIO again on cache's exported object"):
        for i in range(0, core_number):
            Fio().create_command() \
                .io_engine(IoEngine.libaio) \
                .io_depth(64) \
                .size(Size(4, Unit.GibiByte)) \
                .read_write(ReadWrite.randrw) \
                .block_size(Size(64, Unit.MebiByte)) \
                .target(f"{core[i].system_path}") \
                .run()

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()
