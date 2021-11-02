#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import time
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheLineSize,
    CacheMode,
    CacheModeTrait,
    CacheStatus,
    CleaningPolicy,
    PromotionPolicy,
)
from api.cas.casadm import StatsFilter
from api.cas.core import CoreStatus
from api.cas.statistics import (
    usage_stats, request_stats, block_stats_core, block_stats_cache, error_stats
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.size import Size, Unit

# One cache instance per every cache mode:
caches_count = len(CacheMode)
cores_per_cache = 4
# Time to wait after fio (in seconds):
time_to_wait = 30


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_config_stats():
    """
        title: Test CAS configuration information for cache device.
        description: |
          Check CAS ability to display proper configuration information
          in statistics for cache device in every cache mode before and after IO.
        pass_criteria:
          - Cache configuration statistics match cache properties.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches (one for every cache mode) "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_dev, core_dev)

    with TestRun.step(f"Get configuration statistics for each cache and validate them"):
        validate_cache_config_statistics(caches)

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                fio.add_job().target(cores[i][j].path)
        fio_pid = fio.run_in_background()

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check cache configuration statistics after IO"):
        validate_cache_config_statistics(caches, after_io=True)

    with TestRun.step("Stop 'fio'"):
        TestRun.executor.kill_process(fio_pid)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_config_stats():
    """
        title: Test CAS configuration information for core device.
        description: |
          Check CAS ability to display proper configuration information
          in statistics for core device in every cache mode before and after IO.
        pass_criteria:
          - Core configuration statistics match core properties.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches (one for every cache mode) "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_dev, core_dev)

    with TestRun.step(f"Get configuration statistics for each core and validate them"):
        validate_core_config_statistics(cores)

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                fio.add_job().target(cores[i][j].path)
        fio_pid = fio.run_in_background()

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check core configuration statistics after IO"):
        validate_core_config_statistics(cores, caches)

    with TestRun.step("Stop 'fio'"):
        TestRun.executor.kill_process(fio_pid)


@pytest.mark.parametrize(
    "stat_filter",
    [StatsFilter.usage, StatsFilter.req, StatsFilter.blk, StatsFilter.err],
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_nonconfig_stats(stat_filter):
    """
        title: Test CAS statistics for cache device.
        description: |
          Check CAS ability to display usage, request, block and error
          statistics for cache device in every cache mode.
        pass_criteria:
          - All cache statistics can be retrieved.
          - No additional statistics are found.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches (one for every cache mode) "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_dev, core_dev)

    with TestRun.step(f"Get {stat_filter} statistics for each cache and validate them"):
        caches_stats = [
            caches[i].get_statistics_flat(stat_filter=[stat_filter])
            for i in range(caches_count)
        ]
        failed_stats = ""
        for i in range(caches_count):
            failed_stats += validate_statistics_flat(
                caches[i], caches_stats[i], stat_filter, per_core=False
            )

        if failed_stats:
            TestRun.LOGGER.error(
                f"There are some inconsistencies in cache statistics:\n{failed_stats}")


@pytest.mark.parametrize(
    "stat_filter",
    [StatsFilter.usage, StatsFilter.req, StatsFilter.blk, StatsFilter.err],
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_nonconfig_stats(stat_filter):
    """
        title: Test CAS statistics for core device.
        description: |
          Check CAS ability to display usage, request, block and error
          statistics for core device in every cache mode.
        pass_criteria:
          - All core statistics can be retrieved.
          - No additional statistics are found.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches (one for every cache mode) "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_dev, core_dev)

    with TestRun.step(f"Get {stat_filter} statistics for each core and validate them"):
        failed_stats = ""
        for i in range(caches_count):
            cores_stats = [
                cores[i][j].get_statistics_flat(stat_filter=[stat_filter])
                for j in range(cores_per_cache)
            ]
            for j in range(cores_per_cache):
                failed_stats += validate_statistics_flat(
                    cores[i][j], cores_stats[j], stat_filter, per_core=True
                )

        if failed_stats:
            TestRun.LOGGER.error(
                f"There are some inconsistencies in core statistics:\n{failed_stats}")


def storage_prepare():
    cache_dev = TestRun.disks["cache"]
    cache_parts = [Size(20, Unit.GibiByte)] * caches_count
    cache_dev.create_partitions(cache_parts)
    core_dev = TestRun.disks["core"]
    core_parts = [Size(10, Unit.GibiByte)] * cores_per_cache * caches_count
    core_dev.create_partitions(core_parts)

    return cache_dev, core_dev


def cache_prepare(cache_dev, core_dev):
    caches = []
    for i, cache_mode in enumerate(CacheMode):
        caches.append(
            casadm.start_cache(cache_dev.partitions[i], cache_mode, force=True)
        )
    cores = [[] for i in range(caches_count)]
    for i in range(caches_count):
        for j in range(cores_per_cache):
            core_partition_number = i * cores_per_cache + j
            cores[i].append(caches[i].add_core(core_dev.partitions[core_partition_number]))

    return caches, cores


def fio_prepare():
    fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.randrw)
        .direct()
        .run_time(timedelta(minutes=4))
        .time_based()
    )
    return fio


def validate_cache_config_statistics(caches, after_io: bool = False):
    caches_stats = [
        caches[i].get_statistics(stat_filter=[StatsFilter.conf])
        for i in range(caches_count)
    ]
    failed_stats = ""
    for i in range(caches_count):
        if caches_stats[i].config_stats.cache_id != caches[i].cache_id:
            failed_stats += (
                f"For cache number {caches[i].cache_id} cache ID is "
                f"{caches_stats[i].config_stats.cache_id}\n")
        if caches_stats[i].config_stats.cache_dev != caches[i].cache_device.path:
            failed_stats += (
                f"For cache number {caches[i].cache_id} cache device "
                f"is {caches_stats[i].config_stats.cache_dev}, "
                f"should be {caches[i].cache_device.path}\n")
        if caches_stats[i].config_stats.cache_size.value != caches[i].size.value:
            failed_stats += (
                f"For cache number {caches[i].cache_id} cache size is "
                f"{caches_stats[i].config_stats.cache_size.value}, "
                f"should be {caches[i].size.value}\n"
            )
        if caches_stats[i].config_stats.core_dev != cores_per_cache:
            failed_stats += (
                f"For cache number {caches[i].cache_id} number of core devices is "
                f"{caches_stats[i].config_stats.core_dev}, "
                f"should be {cores_per_cache}\n")
        if caches_stats[i].config_stats.inactive_core_dev != 0:
            failed_stats += (
                f"For cache number {caches[i].cache_id} number of inactive core devices is "
                f"{caches_stats[i].config_stats.inactive_core_dev}, should be 0\n")
        if caches_stats[i].config_stats.cleaning_policy.upper() != CleaningPolicy.DEFAULT.value:
            failed_stats += (
                f"For cache number {caches[i].cache_id} cleaning policy is "
                f"{caches_stats[i].config_stats.cleaning_policy.upper()}, "
                f"should be {CleaningPolicy.DEFAULT}\n")
        if caches_stats[i].config_stats.promotion_policy != PromotionPolicy.DEFAULT.value:
            failed_stats += (
                f"For cache number {caches[i].cache_id} promotion policy is "
                f"{caches_stats[i].config_stats.promotion_policy}, "
                f"should be {PromotionPolicy.DEFAULT}\n")
        if caches_stats[i].config_stats.cache_line_size != CacheLineSize.DEFAULT.value:
            failed_stats += (
                f"For cache number {caches[i].cache_id} cache line size is "
                f"{caches_stats[i].config_stats.cache_line_size}, "
                f"should be {CacheLineSize.DEFAULT.value}\n")
        if (
            CacheStatus[caches_stats[i].config_stats.status.replace(' ', '_').lower()]
            != CacheStatus.running
        ):
            failed_stats += (
                f"For cache number {caches[i].cache_id} cache status is "
                f"{caches_stats[i].config_stats.status}, should be Running\n")
        if after_io:
            cache_mode = CacheMode[caches_stats[i].config_stats.write_policy.upper()]
            if CacheModeTrait.LazyWrites in CacheMode.get_traits(cache_mode):
                if caches_stats[i].config_stats.dirty_for.total_seconds() <= 0:
                    failed_stats += (
                        f"For cache number {caches[i].cache_id} in {cache_mode} "
                        f"cache mode, value of 'Dirty for' after IO is "
                        f"{caches_stats[i].config_stats.dirty_for}, "
                        f"should be greater then 0\n")
            else:
                if caches_stats[i].config_stats.dirty_for.total_seconds() != 0:
                    failed_stats += (
                        f"For cache number {caches[i].cache_id} in {cache_mode} "
                        f"cache mode, value of 'Dirty for' after IO is "
                        f"{caches_stats[i].config_stats.dirty_for}, "
                        f"should equal 0\n")
        else:
            if caches_stats[i].config_stats.dirty_for.total_seconds() < 0:
                failed_stats += (
                    f"For cache number {caches[i].cache_id} value of 'Dirty for' "
                    f"is {caches_stats[i].config_stats.dirty_for}, "
                    f"should be greater or equal 0\n")

    if failed_stats:
        TestRun.LOGGER.error(
            f"There are some inconsistencies in cache "
            f"configuration statistics:\n{failed_stats}")


def validate_core_config_statistics(cores, caches=None):
    failed_stats = ""
    for i in range(caches_count):
        cores_stats = [
            cores[i][j].get_statistics(stat_filter=[StatsFilter.conf])
            for j in range(cores_per_cache)
        ]
        for j in range(cores_per_cache):
            if cores_stats[j].config_stats.exp_obj != cores[i][j].path:
                failed_stats += (
                    f"For exported object {cores[i][j].path} "
                    f"value in stats is {cores_stats[j].config_stats.exp_obj}\n")
            if cores_stats[j].config_stats.core_id != cores[i][j].core_id:
                failed_stats += (
                    f"For exported object {cores[i][j].path} "
                    f"core ID is {cores_stats[j].config_stats.core_id}, "
                    f"should be {cores[i][j].core_id}\n")
            if cores_stats[j].config_stats.core_dev != cores[i][j].core_device.path:
                failed_stats += (
                    f"For exported object {cores[i][j].path} "
                    f"core device is {cores_stats[j].config_stats.core_dev}, "
                    f"should be {cores[i][j].core_device.path}\n")
            if cores_stats[j].config_stats.core_size.value != cores[i][j].size.value:
                failed_stats += (
                    f"For exported object {cores[i][j].path} "
                    f"core size is {cores_stats[j].config_stats.core_size.value}, "
                    f"should be {cores[i][j].size.value}\n")
            if (
                CoreStatus[cores_stats[j].config_stats.status.lower()]
                != cores[i][j].get_status()
            ):
                failed_stats += (
                    f"For exported object {cores[i][j].path} core "
                    f"status is {cores_stats[j].config_stats.status}, should be "
                    f"{str(cores[i][j].get_status()).split('.')[1].capitalize()}\n")
            if cores_stats[j].config_stats.seq_cutoff_policy is None:
                failed_stats += (
                    f"For exported object {cores[i][j].path} value of "
                    f"Sequential cut-off policy should not be empty\n")
            if cores_stats[j].config_stats.seq_cutoff_threshold.value <= 0:
                failed_stats += (
                    f"For exported object {cores[i][j].path} value of "
                    f"Sequential cut-off threshold should be greater then 0\n")
            if caches:
                cache_mode = CacheMode[
                    caches[i].get_statistics().config_stats.write_policy.upper()
                ]
                if CacheModeTrait.LazyWrites in CacheMode.get_traits(cache_mode):
                    if cores_stats[j].config_stats.dirty_for.total_seconds() <= 0:
                        failed_stats += (
                            f"For exported object {cores[i][j].path} in "
                            f"{cache_mode} cache mode, value of 'Dirty for' "
                            f"after IO is {cores_stats[j].config_stats.dirty_for}, "
                            f"should be greater then 0\n")
                else:
                    if cores_stats[j].config_stats.dirty_for.total_seconds() != 0:
                        failed_stats += (
                            f"For exported object {cores[i][j].path} in "
                            f"{cache_mode} cache mode, value of 'Dirty for' "
                            f"after IO is {cores_stats[j].config_stats.dirty_for}, "
                            f"should equal 0\n")
            else:
                if cores_stats[j].config_stats.dirty_for.total_seconds() < 0:
                    failed_stats += (
                        f"For exported object {cores[i][j].path} value of "
                        f"'Dirty for' is {cores_stats[j].config_stats.dirty_for}, "
                        f"should be greater or equal 0\n")

    if failed_stats:
        TestRun.LOGGER.error(
            f"There are some inconsistencies in core "
            f"configuration statistics:\n{failed_stats}")


def validate_statistics_flat(device, stats, stat_filter, per_core: bool):
    device_name = (
        f"core device {device.path}" if per_core else
        f"cache number {device.cache_id}")
    failed_stats = ""
    if stat_filter == StatsFilter.usage:
        current_stats = usage_stats
    if stat_filter == StatsFilter.blk:
        current_stats = block_stats_core if per_core else block_stats_cache
    if stat_filter == StatsFilter.req:
        current_stats = request_stats
    if stat_filter == StatsFilter.err:
        current_stats = error_stats

    for stat_name in current_stats:
        if stat_name not in stats.keys():
            failed_stats += (
                f"For {device_name} value for {stat_name} not displayed in output\n")
        else:
            del stats[stat_name]
    if len(stats.keys()):
        failed_stats += (
            f"Additional statistics found for {device_name}: {', '.join(stats.keys())}\n")

    return failed_stats
