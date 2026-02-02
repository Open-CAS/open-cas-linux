#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import (CleaningPolicy,
                                  CacheMode,
                                  CacheModeTrait,
                                  CacheLineSize,
                                  FlushParametersAlru,
                                  Time,
                                  FlushParametersAcp)
from api.cas.casadm_params import StatsFilter
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite, CpusAllowedPolicy
from type_def.size import Size, Unit


@pytest.mark.parametrizex("cores_amount", [1, 4])
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_x_cores_to_one_cache(cache_mode, cleaning_policy, cache_line_size, cores_amount):
    """
        title: Test for loading CAS with 1 cache and 1 or 4 cores without extra params.
        description: |
          Verify that loading cache configurations works properly in every mode
          with 1 cache and 1 or 4 cores.
        pass_criteria:
          - Cache loads successfully.
          - No errors in cache are found.
    """
    with TestRun.step(f"Prepare 1 cache and {cores_amount} core devices"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(512, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_size = []
        for i in range(cores_amount):
            core_size.append(Size(1, Unit.GibiByte))
        core_dev.create_partitions(core_size)

    with TestRun.step(f"Start cache with {cores_amount} cores."):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
        cores = []
        for i in range(cores_amount):
            cores.append(cache.add_core(core_dev.partitions[i]))
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != cores_amount:
            TestRun.fail(
                f"Expected cores count: {cores_amount}; Actual cores count: {cores_count}.")

    with TestRun.step("Configure cleaning policy."):
        cache.set_cleaning_policy(cleaning_policy)
        if cleaning_policy == CleaningPolicy.alru:
            alru = FlushParametersAlru()
            alru.activity_threshold = Time(milliseconds=1000)
            alru.flush_max_buffers = 10
            alru.staleness_time = Time(seconds=60)
            alru.wake_up_time = Time(seconds=5)
            alru.dirty_ratio_threshold = 75
            alru.dirty_ratio_inertia = Size(15, Unit.MebiByte)
            cache.set_params_alru(alru)
        if cleaning_policy == CleaningPolicy.acp:
            acp = FlushParametersAcp()
            acp.flush_max_buffers = 100
            acp.wake_up_time = Time(seconds=5)
            cache.set_params_acp(acp)

    with TestRun.step("Run FIO on exported object"):
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .io_depth(64)
               .direct()
               .read_write(ReadWrite.randrw)
               .size(Size(1, Unit.GibiByte))
               .block_size(cache_line_size)
               .read_write(ReadWrite.randrw)
               .num_jobs(cores_amount)
               .cpus_allowed_policy(CpusAllowedPolicy.split))
        for core in cores:
            fio.add_job(f"job_{core.core_id}").target(core.path)
        fio.run()

    with TestRun.step("Stop cache."):
        cache.stop()
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"There are still {caches_count} caches running after stopping service.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 0:
            TestRun.fail(f"There are still {cores_count} cores running after stopping service.")

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != cores_amount:
            TestRun.fail(
                f"Expected cores count: {cores_amount}; Actual cores count: {cores_count}.")

    with TestRun.step("Compare cache configuration before and after load."):
        if cache_mode != cache.get_cache_mode():
            TestRun.fail("Cache modes are different.")
        if cache_line_size != cache.get_cache_line_size():
            TestRun.fail("Cache line sizes are different.")
        if cleaning_policy != cache.get_cleaning_policy():
            TestRun.fail("Cleaning policies are different.")
        if cleaning_policy == CleaningPolicy.alru:
            if alru != cache.get_flush_parameters_alru():
                TestRun.fail("Cleaning policy parameters are different.")
        if cleaning_policy == CleaningPolicy.acp:
            if acp != cache.get_flush_parameters_acp():
                TestRun.fail("Cleaning policy parameters are different.")

    with TestRun.step("Run FIO again on exported object"):
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .io_depth(64)
               .direct()
               .read_write(ReadWrite.randrw)
               .size(Size(1, Unit.GibiByte))
               .block_size(cache_line_size)
               .read_write(ReadWrite.randrw)
               .num_jobs(cores_amount)
               .cpus_allowed_policy(CpusAllowedPolicy.split))
        for core in cores:
            fio.add_job(f"job_{core.core_id}").target(core.path)
        fio.run()

    with TestRun.step("Check if there are no error statistics."):
        if cache.get_statistics().error_stats.total_errors != 0:
            TestRun.fail("There are errors in the cache.")

@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_cache_dirty(cache_mode, cache_line_size, cleaning_policy):
    """
        title: Load cache with dirty data after stopping it without flush
        description: |
          Verify that cache loads properly after being stopped with dirty data and no flush.
        pass_criteria:
          - Cache loads successfully.
          - There is dirty data on the cache after load.
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(512, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Configure cleaning policy"):
        cache.set_cleaning_policy(cleaning_policy)
        if cleaning_policy == CleaningPolicy.alru:
            alru = FlushParametersAlru()
            alru.wake_up_time = Time(seconds=5)
            cache.set_params_alru(alru)
        if cleaning_policy == CleaningPolicy.acp:
            acp = FlushParametersAcp()
            acp.wake_up_time = Time(seconds=5)
            cache.set_params_acp(acp)

    with TestRun.step("Run FIO on exported object"):
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .read_write(ReadWrite.write)
               .block_size(cache_line_size)
               .io_depth(64)
               .direct()
               .sync()
               .size(Size(1, Unit.GibiByte))
               .target(core.path)
        )
        fio.run()

    with TestRun.step("Verify that cache has dirty data"):
        cache_stats = cache.get_statistics([StatsFilter.usage], percentage_val=True)
        if cache_stats.usage_stats.dirty < 0.5:
            TestRun.block("Ditry lower than 50%")

    with TestRun.step("Stop cache without flush"):
        cache.stop(no_data_flush=True)

    with TestRun.step("Load cache"):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Verify that cache still has dirty data"):
        cache_stats = cache.get_statistics([StatsFilter.usage], percentage_val=True)
        if cache_stats.usage_stats.dirty < 0.5:
            TestRun.fail("Ditry lower than 50%")

    with TestRun.step("Stop cache"):
        cache.stop()
