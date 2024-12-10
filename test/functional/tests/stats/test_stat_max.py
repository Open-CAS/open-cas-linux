#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from time import sleep

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy
from api.cas.casadm import StatsFilter
from api.cas.statistics import get_stats_dict, get_stat_value
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.os_utils import Udev
from types.size import Size, Unit

cache_size = Size(1, Unit.GibiByte)
core_size = Size(2, Unit.GibiByte)
io_size = Size(10, Unit.MebiByte)
stat_filter = [StatsFilter.usage, StatsFilter.req, StatsFilter.blk]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stat_max_cache():
    """
        title: CAS statistics values for maximum cache devices.
        description: |
          Check CAS ability to display correct values in statistics
          for 16 cache devices per cache mode.
        pass_criteria:
          - Cores' statistics match cache's statistics.
    """

    caches_per_cache_mode = 16
    cores_per_cache = 1
    caches_count = caches_per_cache_mode * len(CacheMode)

    with TestRun.step(
        f"Create {caches_count} cache and "
        f"{cores_per_cache * caches_count} core partitions"
    ):
        cache_dev = TestRun.disks["cache"]
        cache_parts = [cache_size] * caches_count
        cache_dev.create_partitions(cache_parts)
        core_dev = TestRun.disks["core"]
        core_parts = [core_size] * cores_per_cache * caches_count
        core_dev.create_partitions(core_parts)
        Udev.disable()

    with TestRun.step(
        f"Start {caches_count} caches ({caches_per_cache_mode} for "
        f"every cache mode) and add {cores_per_cache} core(s) per cache"
    ):
        caches = []
        cores = [[] for i in range(caches_count)]
        for i, cache_mode in enumerate(CacheMode):
            for j in range(caches_per_cache_mode):
                cache_partition_number = i * caches_per_cache_mode + j
                caches.append(casadm.start_cache(
                    cache_dev.partitions[cache_partition_number],
                    cache_mode=cache_mode,
                    force=True
                ))
        for i in range(caches_count):
            caches[i].set_cleaning_policy(CleaningPolicy.nop)
            for j in range(cores_per_cache):
                core_partition_number = i * cores_per_cache + j
                cores[i].append(
                    caches[i].add_core(core_dev.partitions[core_partition_number])
                )

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                fio.add_job().target(cores[i][j].path)
        fio.run()
        sleep(3)

    with TestRun.step("Check if cache's statistics match cores' statistics"):
        for i in range(caches_count):
            cache_stats = get_stats_dict(filter=stat_filter, cache_id=caches[i].cache_id)
            cores_stats = [
                get_stats_dict(
                    filter=stat_filter, cache_id=caches[i].cache_id, core_id=cores[i][j].core_id
                ) for j in range(cores_per_cache)
            ]
            fail_message = f"For cache ID {caches[i].cache_id} ({caches[i].get_cache_mode()}) "
            stats_compare(cache_stats, cores_stats, cores_per_cache, fail_message)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_stat_max_core(cache_mode):
    """
        title: CAS statistics values for maximum core devices.
        description: |
          Check CAS ability to display correct values in statistics
          for 62 core devices.
        pass_criteria:
          - Cores' statistics match cache's statistics.
    """

    cores_per_cache = 62

    with TestRun.step(f"Create 1 cache and {cores_per_cache} core partitions"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([cache_size])
        core_dev = TestRun.disks["core"]
        core_parts = [core_size] * cores_per_cache
        core_dev.create_partitions(core_parts)
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} cache mode and add {cores_per_cache} cores"):
        cache = casadm.start_cache(
            cache_dev.partitions[0], cache_mode=cache_mode, force=True
        )
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cores = []
        for j in range(cores_per_cache):
            cores.append(cache.add_core(core_dev.partitions[j]))

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for j in range(cores_per_cache):
            fio.add_job().target(cores[j].path)
        fio.run()
        sleep(3)

    with TestRun.step("Check if cache's statistics match cores' statistics"):
        cache_stats = get_stats_dict(filter=stat_filter, cache_id=cache.cache_id)
        cores_stats = [
            get_stats_dict(
                filter=stat_filter, cache_id=cache.cache_id, core_id=cores[j].core_id
            ) for j in range(cores_per_cache)
        ]
        fail_message = f"In {cache_mode} cache mode "
        stats_compare(cache_stats, cores_stats, cores_per_cache, fail_message)


def fio_prepare():
    fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.randwrite)
        .size(io_size)
        .direct()
    )

    return fio


def stats_compare(cache_stats, cores_stats, cores_per_cache, fail_message):
    for stat_name in cache_stats.keys():
        if stat_name.startswith("Free ") or stat_name.endswith("[%]"):
            continue
        core_stat_sum = 0
        try:
            cache_stats[stat_name] = get_stat_value(cache_stats, stat_name)
            for j in range(cores_per_cache):
                cores_stats[j][stat_name] = get_stat_value(cores_stats[j], stat_name)
        except AttributeError:
            pass
        for j in range(cores_per_cache):
            core_stat_sum += cores_stats[j][stat_name]
        if core_stat_sum != cache_stats[stat_name]:
            TestRun.LOGGER.error(fail_message + (
                f"sum of cores' '{stat_name}' values is "
                f"{core_stat_sum}, should equal cache value: "
                f"{cache_stats[stat_name]}\n"))
