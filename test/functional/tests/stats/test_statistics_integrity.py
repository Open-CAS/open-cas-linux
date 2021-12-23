#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait
from api.cas.casadm import StatsFilter
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit
from time import sleep


# One cache instance per every cache mode:
caches_count = len(CacheMode)
cores_per_cache = 4
cache_size = Size(20, Unit.GibiByte)
core_size = Size(10, Unit.GibiByte)
io_value = 1000
io_size = Size(io_value, Unit.Blocks4096)
# Error stats not included in 'stat_filter' because all of them
# should equal 0 and can be checked easier, shorter way.
stat_filter = [StatsFilter.usage, StatsFilter.req, StatsFilter.blk]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stats_values():
    """
        title: Check for proper statistics values.
        description: |
          Check if CAS displays proper usage, request, block and error statistics values
          for core devices in every cache mode - at the start, after IO and after cache
          reload. Also check if core's statistics match cache's statistics.
        pass_criteria:
          - Usage, request, block and error statistics have proper values.
          - Core's statistics match cache's statistics.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()
        Udev.disable()

    with TestRun.step(
        f"Start {caches_count} caches (one for every cache mode) "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_dev, core_dev)

    with TestRun.step("Check initial statistics values for each core"):
        check_stats_initial(caches, cores)

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                fio.add_job().target(cores[i][j].path)
        fio.run()
        sleep(3)

    with TestRun.step("Check statistics values after IO"):
        check_stats_after_io(caches, cores)

    with TestRun.step("Check if cache's statistics match core's statistics"):
        check_stats_sum(caches, cores)

    with TestRun.step("Stop and load caches back"):
        casadm.stop_all_caches()
        caches = cache_load(cache_dev)

    with TestRun.step("Check statistics values after reload"):
        check_stats_after_io(caches, cores, after_reload=True)


def storage_prepare():
    cache_dev = TestRun.disks["cache"]
    cache_parts = [cache_size] * caches_count
    cache_dev.create_partitions(cache_parts)
    core_dev = TestRun.disks["core"]
    core_parts = [core_size] * cores_per_cache * caches_count
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


def cache_load(cache_dev):
    caches = []
    for i in range(caches_count):
        caches.append(casadm.load_cache(cache_dev.partitions[i]))

    return caches


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


def get_stats_flat(cores, cache=None, stat_filter=stat_filter):
    if cache:
        cache_stats = cache.get_statistics_flat(stat_filter=stat_filter)
    cores_stats = [
        cores[j].get_statistics_flat(stat_filter=stat_filter)
        for j in range(cores_per_cache)
    ]
    cores_stats_perc = [
        cores[j].get_statistics_flat(stat_filter=stat_filter, percentage_val=True)
        for j in range(cores_per_cache)
    ]

    if cache:
        return cores_stats, cores_stats_perc, cache_stats
    else:
        return cores_stats, cores_stats_perc


def check_stats_initial(caches, cores):
    for i in range(caches_count):
        cores_stats, cores_stats_perc = get_stats_flat(cores[i])
        for j in range(cores_per_cache):
            for stat_name, stat_value in cores_stats[j].items():
                try:
                    stat_value = stat_value.value
                except AttributeError:
                    pass
                if stat_name.lower() == "free":
                    if stat_value != caches[i].size.value:
                        TestRun.LOGGER.error(
                            f"For core device {cores[i][j].path} "
                            f"value for '{stat_name}' is {stat_value}, "
                            f"should equal cache size: {caches[i].size.value}\n")
                elif stat_value != 0:
                    TestRun.LOGGER.error(
                        f"For core device {cores[i][j].path} value for "
                        f"'{stat_name}' is {stat_value}, should equal 0\n")
            for stat_name, stat_value in cores_stats_perc[j].items():
                if stat_name.lower() == "free":
                    if stat_value != 100:
                        TestRun.LOGGER.error(
                            f"For core device {cores[i][j].path} percentage value "
                            f"for '{stat_name}' is {stat_value}, should equal 100\n")
                elif stat_value != 0:
                    TestRun.LOGGER.error(
                        f"For core device {cores[i][j].path} percentage value "
                        f"for '{stat_name}' is {stat_value}, should equal 0\n")


def check_stats_after_io(caches, cores, after_reload: bool = False):
    for i in range(caches_count):
        cache_mode = caches[i].get_cache_mode()
        cores_stats = [
            cores[i][j].get_statistics(stat_filter=stat_filter)
            for j in range(cores_per_cache)
        ]
        cores_stats_perc = [
            cores[i][j].get_statistics(stat_filter=stat_filter, percentage_val=True)
            for j in range(cores_per_cache)
        ]
        cores_error_stats, cores_error_stats_perc = get_stats_flat(
            cores[i], stat_filter=[StatsFilter.err]
        )
        for j in range(cores_per_cache):
            fail_message = (
                f"For core device {cores[i][j].path} in {cache_mode} cache mode ")
            if after_reload:
                validate_usage_stats(
                    cores_stats[j], cores_stats_perc[j], caches[i], cache_mode, fail_message)
                validate_error_stats(
                    cores_error_stats[j], cores_error_stats_perc[j], cache_mode, fail_message)
            else:
                validate_usage_stats(
                    cores_stats[j], cores_stats_perc[j], caches[i], cache_mode, fail_message)
                validate_request_stats(
                    cores_stats[j], cores_stats_perc[j], cache_mode, fail_message)
                validate_block_stats(
                    cores_stats[j], cores_stats_perc[j], cache_mode, fail_message)
                validate_error_stats(
                    cores_error_stats[j], cores_error_stats_perc[j], cache_mode, fail_message)


def check_stats_sum(caches, cores):
    for i in range(caches_count):
        cores_stats, cores_stats_perc, cache_stats = (
            get_stats_flat(cores[i], cache=caches[i])
        )
        for cache_stat_name in cache_stats.keys():
            if cache_stat_name.lower() != "free":
                core_stat_name = cache_stat_name.replace("(s)", "")
                core_stat_sum = 0
                try:
                    cache_stats[cache_stat_name] = cache_stats[cache_stat_name].value
                    for j in range(cores_per_cache):
                        cores_stats[j][core_stat_name] = cores_stats[j][core_stat_name].value
                except AttributeError:
                    pass
                for j in range(cores_per_cache):
                    core_stat_sum += cores_stats[j][core_stat_name]
                if core_stat_sum != cache_stats[cache_stat_name]:
                    TestRun.LOGGER.error(
                        f"For cache ID {caches[i].cache_id} sum of core's "
                        f"'{core_stat_name}' values is {core_stat_sum}, "
                        f"should equal {cache_stats[cache_stat_name]}\n")


def validate_usage_stats(stats, stats_perc, cache, cache_mode, fail_message):
    fail_message += f"in 'usage' stats"
    if cache_mode not in CacheMode.with_traits(CacheModeTrait.InsertWrite):
        if stats.usage_stats.occupancy.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'occupancy' is "
                f"{stats.usage_stats.occupancy.value}, "
                f"should equal 0\n")
        if stats_perc.usage_stats.occupancy != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'occupancy' percentage is "
                f"{stats_perc.usage_stats.occupancy}, "
                f"should equal 0\n")
        if stats.usage_stats.free != cache.size:
            TestRun.LOGGER.error(
                f"{fail_message} 'free' is "
                f"{stats.usage_stats.free.value}, "
                f"should equal cache size: {cache.size.value}\n")
        if stats_perc.usage_stats.free != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'free' percentage is "
                f"{stats_perc.usage_stats.free}, "
                f"should equal 100\n")
        if stats.usage_stats.clean.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'clean' is "
                f"{stats.usage_stats.clean.value}, "
                f"should equal 0\n")
        if stats_perc.usage_stats.clean != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'clean' percentage is "
                f"{stats_perc.usage_stats.clean}, "
                f"should equal 0\n")
        if stats.usage_stats.dirty.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'dirty' is "
                f"{stats.usage_stats.dirty.value}, "
                f"should equal 0\n")
        if stats_perc.usage_stats.dirty != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'dirty' percentage is "
                f"{stats_perc.usage_stats.dirty}, "
                f"should equal 0\n")
    else:
        occupancy_perc = round(100 * io_size.value / cache.size.value, 1)
        free = cache.size.value - io_size.value * cores_per_cache
        free_perc = round(100 * (cache.size.value - io_size.value
                          * cores_per_cache) / cache.size.value, 1)
        if stats.usage_stats.occupancy.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'occupancy' is "
                f"{stats.usage_stats.occupancy.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.usage_stats.occupancy != occupancy_perc:
            TestRun.LOGGER.error(
                f"{fail_message} 'occupancy' percentage is "
                f"{stats_perc.usage_stats.occupancy}, "
                f"should equal {occupancy_perc}\n")
        if stats.usage_stats.free.value != free:
            TestRun.LOGGER.error(
                f"{fail_message} 'free' is "
                f"{stats.usage_stats.free.value}, "
                f"should equal {free}\n")
        if stats_perc.usage_stats.free != free_perc:
            TestRun.LOGGER.error(
                f"{fail_message} 'free' percentage is "
                f"{stats_perc.usage_stats.free}, "
                f"should equal {free_perc}\n")
        if cache_mode not in CacheMode.with_traits(CacheModeTrait.LazyWrites):
            if stats.usage_stats.clean.value != io_size.value:
                TestRun.LOGGER.error(
                    f"{fail_message} 'clean' is "
                    f"{stats.usage_stats.clean.value}, "
                    f"should equal IO size: {io_size.value}\n")
            if stats_perc.usage_stats.clean != 100:
                TestRun.LOGGER.error(
                    f"{fail_message} 'clean' percentage is "
                    f"{stats_perc.usage_stats.clean}, "
                    f"should equal 100\n")
            if stats.usage_stats.dirty.value != 0:
                TestRun.LOGGER.error(
                    f"{fail_message} 'dirty' is "
                    f"{stats.usage_stats.dirty.value}, "
                    f"should equal 0\n")
            if stats_perc.usage_stats.dirty != 0:
                TestRun.LOGGER.error(
                    f"{fail_message} 'dirty' percentage is "
                    f"{stats_perc.usage_stats.dirty}, "
                    f"should equal 0\n")
        else:
            if stats.usage_stats.clean.value != 0:
                TestRun.LOGGER.error(
                    f"{fail_message} 'clean' is "
                    f"{stats.usage_stats.clean.value}, "
                    f"should equal 0\n")
            if stats_perc.usage_stats.clean != 0:
                TestRun.LOGGER.error(
                    f"{fail_message} 'clean' percentage is "
                    f"{stats_perc.usage_stats.clean}, "
                    f"should equal 0\n")
            if stats.usage_stats.dirty.value != io_size.value:
                TestRun.LOGGER.error(
                    f"{fail_message} 'dirty' is "
                    f"{stats.usage_stats.dirty.value}, "
                    f"should equal IO size: {io_size.value}\n")
            if stats_perc.usage_stats.dirty != 100:
                TestRun.LOGGER.error(
                    f"{fail_message} 'dirty' percentage is "
                    f"{stats_perc.usage_stats.dirty}, "
                    f"should equal 100\n")


def validate_request_stats(stats, stats_perc, cache_mode, fail_message):
    fail_message += f"in 'request' stats"
    if stats.request_stats.read.hits != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read hits' is "
            f"{stats.request_stats.read.hits}, "
            f"should equal 0\n")
    if stats_perc.request_stats.read.hits != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read hits' percentage is "
            f"{stats_perc.request_stats.read.hits}, "
            f"should equal 0\n")
    if stats.request_stats.read.part_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read partial misses' is "
            f"{stats.request_stats.read.part_misses}, "
            f"should equal 0\n")
    if stats_perc.request_stats.read.part_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read partial misses' percentage is "
            f"{stats_perc.request_stats.read.part_misses}, "
            f"should equal 0\n")
    if stats.request_stats.read.full_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read full misses' is "
            f"{stats.request_stats.read.full_misses}, "
            f"should equal 0\n")
    if stats_perc.request_stats.read.full_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read full misses' percentage is "
            f"{stats_perc.request_stats.read.full_misses}, "
            f"should equal 0\n")
    if stats.request_stats.read.total != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read total' is "
            f"{stats.request_stats.read.total}, "
            f"should equal 0\n")
    if stats_perc.request_stats.read.total != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Read total' percentage is "
            f"{stats_perc.request_stats.read.total}, "
            f"should equal 0\n")
    if stats.request_stats.write.hits != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Write hits' is "
            f"{stats.request_stats.write.hits}, "
            f"should equal 0\n")
    if stats_perc.request_stats.write.hits != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Write hits' percentage is "
            f"{stats_perc.request_stats.write.hits}, "
            f"should equal 0\n")
    if stats.request_stats.write.part_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Write partial misses' is "
            f"{stats.request_stats.write.part_misses}, "
            f"should equal 0\n")
    if stats_perc.request_stats.write.part_misses != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Write partial misses' percentage is "
            f"{stats_perc.request_stats.write.part_misses}, "
            f"should equal 0\n")
    if stats.request_stats.pass_through_reads != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Pass-through reads' is "
            f"{stats.request_stats.pass_through_reads}, "
            f"should equal 0\n")
    if stats_perc.request_stats.pass_through_reads != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Pass-through reads' percentage is "
            f"{stats_perc.request_stats.pass_through_reads}, "
            f"should equal 0\n")
    if stats.request_stats.requests_total != io_value:
        TestRun.LOGGER.error(
            f"{fail_message} 'Total requests' is "
            f"{stats.request_stats.requests_total}, "
            f"should equal IO size value: {io_value}\n")
    if stats_perc.request_stats.requests_total != 100:
        TestRun.LOGGER.error(
            f"{fail_message} 'Total requests' percentage is "
            f"{stats_perc.request_stats.requests_total}, "
            f"should equal 100\n")
    if cache_mode in CacheMode.with_traits(CacheModeTrait.InsertWrite):
        if stats.request_stats.write.full_misses != io_value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write full misses' is "
                f"{stats.request_stats.write.full_misses}, "
                f"should equal IO size value: {io_value}\n")
        if stats_perc.request_stats.write.full_misses != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write full misses' percentage is "
                f"{stats_perc.request_stats.write.full_misses}, "
                f"should equal 100\n")
        if stats.request_stats.write.total != io_value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write total' is "
                f"{stats.request_stats.write.total}, "
                f"should equal IO size value: {io_value}\n")
        if stats_perc.request_stats.write.total != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write total' percentage is "
                f"{stats_perc.request_stats.write.total}, "
                f"should equal 100\n")
        if stats.request_stats.pass_through_writes != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Pass-through writes' is "
                f"{stats.request_stats.pass_through_writes}, "
                f"should equal 0\n")
        if stats_perc.request_stats.pass_through_writes != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Pass-through writes' percentage is "
                f"{stats_perc.request_stats.pass_through_writes}, "
                f"should equal 0\n")
        if stats.request_stats.requests_serviced != io_value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Serviced requests' is "
                f"{stats.request_stats.requests_serviced}, "
                f"should equal IO size value: {io_value}\n")
        if stats_perc.request_stats.requests_serviced != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Serviced requests' percentage is "
                f"{stats_perc.request_stats.requests_serviced}, "
                f"should equal 100\n")
    else:
        if stats.request_stats.write.full_misses != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write full misses' is "
                f"{stats.request_stats.write.full_misses}, "
                f"should equal 0\n")
        if stats_perc.request_stats.write.full_misses != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write full misses' percentage is "
                f"{stats_perc.request_stats.write.full_misses}, "
                f"should equal 0\n")
        if stats.request_stats.write.total != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write total' is "
                f"{stats.request_stats.write.total}, "
                f"should equal 0\n")
        if stats_perc.request_stats.write.total != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Write total' percentage is "
                f"{stats_perc.request_stats.write.total}, "
                f"should equal 0\n")
        if stats.request_stats.pass_through_writes != io_value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Pass-through writes' is "
                f"{stats.request_stats.pass_through_writes}, "
                f"should equal IO size value: {io_value}\n")
        if stats_perc.request_stats.pass_through_writes != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Pass-through writes' percentage is "
                f"{stats_perc.request_stats.pass_through_writes}, "
                f"should equal 100\n")
        if stats.request_stats.requests_serviced != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Serviced requests' is "
                f"{stats.request_stats.requests_serviced}, "
                f"should equal 0\n")
        if stats_perc.request_stats.requests_serviced != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Serviced requests' percentage is "
                f"{stats_perc.request_stats.requests_serviced}, "
                f"should equal 0\n")


def validate_block_stats(stats, stats_perc, cache_mode, fail_message):
    fail_message += f"in 'block' stats"
    if stats.block_stats.core.reads.value != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Core reads' is "
            f"{stats.block_stats.core.reads.value}, "
            f"should equal 0\n")
    if stats_perc.block_stats.core.reads != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Core reads' percentage is "
            f"{stats_perc.block_stats.core.reads}, "
            f"should equal 0\n")
    if stats.block_stats.cache.reads.value != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Cache reads' is "
            f"{stats.block_stats.cache.reads.value}, "
            f"should equal 0\n")
    if stats_perc.block_stats.cache.reads != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Cache reads' percentage is "
            f"{stats_perc.block_stats.cache.reads}, "
            f"should equal 0\n")
    if stats.block_stats.exp_obj.reads.value != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object reads' is "
            f"{stats.block_stats.exp_obj.reads.value}, "
            f"should equal 0\n")
    if stats_perc.block_stats.exp_obj.reads != 0:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object reads' percentage is "
            f"{stats_perc.block_stats.exp_obj.reads}, "
            f"should equal 0\n")
    if stats.block_stats.exp_obj.writes.value != io_size.value:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object writes' is "
            f"{stats.block_stats.exp_obj.writes.value}, "
            f"should equal IO size: {io_size.value}\n")
    if stats_perc.block_stats.exp_obj.writes != 100:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object writes' percentage is "
            f"{stats_perc.block_stats.exp_obj.writes}, "
            f"should equal 100\n")
    if stats.block_stats.exp_obj.total.value != io_size.value:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object total' is "
            f"{stats.block_stats.exp_obj.total.value}, "
            f"should equal IO size: {io_size.value}\n")
    if stats_perc.block_stats.exp_obj.total != 100:
        TestRun.LOGGER.error(
            f"{fail_message} 'Exported object total' percentage is "
            f"{stats_perc.block_stats.exp_obj.total}, "
            f"should equal 100\n")
    if cache_mode not in CacheMode.with_traits(CacheModeTrait.InsertWrite):
        if stats.block_stats.core.writes.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' is "
                f"{stats.block_stats.core.writes.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.core.writes != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' percentage is "
                f"{stats_perc.block_stats.core.writes}, "
                f"should equal 100\n")
        if stats.block_stats.core.total.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' is "
                f"{stats.block_stats.core.total.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.core.total != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' percentage is "
                f"{stats_perc.block_stats.core.total}, "
                f"should equal 100\n")
        if stats.block_stats.cache.writes.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' is "
                f"{stats.block_stats.cache.writes.value}, "
                f"should equal 0\n")
        if stats_perc.block_stats.cache.writes != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' percentage is "
                f"{stats_perc.block_stats.cache.writes}, "
                f"should equal 0\n")
        if stats.block_stats.cache.total.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' is "
                f"{stats.block_stats.cache.total.value}, "
                f"should equal 0\n")
        if stats_perc.block_stats.cache.total != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' percentage is "
                f"{stats_perc.block_stats.cache.total}, "
                f"should equal 0\n")
    elif cache_mode in CacheMode.with_traits(
        CacheModeTrait.InsertWrite | CacheModeTrait.LazyWrites
    ):
        if stats.block_stats.core.writes.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' is "
                f"{stats.block_stats.core.writes.value}, "
                f"should equal 0\n")
        if stats_perc.block_stats.core.writes != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' percentage is "
                f"{stats_perc.block_stats.core.writes}, "
                f"should equal 0\n")
        if stats.block_stats.core.total.value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' is "
                f"{stats.block_stats.core.total.value}, "
                f"should equal 0\n")
        if stats_perc.block_stats.core.total != 0:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' percentage is "
                f"{stats_perc.block_stats.core.total}, "
                f"should equal 0\n")
        if stats.block_stats.cache.writes.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' is "
                f"{stats.block_stats.cache.writes.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.cache.writes != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' percentage is "
                f"{stats_perc.block_stats.cache.writes}, "
                f"should equal 100\n")
        if stats.block_stats.cache.total.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' is "
                f"{stats.block_stats.cache.total.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.cache.total != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' percentage is "
                f"{stats_perc.block_stats.cache.total}, "
                f"should equal 100\n")
    elif (
        cache_mode in CacheMode.with_traits(CacheModeTrait.InsertWrite)
        and cache_mode not in CacheMode.with_traits(CacheModeTrait.LazyWrites)
    ):
        if stats.block_stats.core.writes.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' is "
                f"{stats.block_stats.core.writes.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.core.writes != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core writes' percentage is "
                f"{stats_perc.block_stats.core.writes}, "
                f"should equal 100\n")
        if stats.block_stats.core.total.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' is "
                f"{stats.block_stats.core.total.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.core.total != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Core total' percentage is "
                f"{stats_perc.block_stats.core.total}, "
                f"should equal 100\n")
        if stats.block_stats.cache.writes.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' is "
                f"{stats.block_stats.cache.writes.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.cache.writes != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache writes' percentage is "
                f"{stats_perc.block_stats.cache.writes}, "
                f"should equal 100\n")
        if stats.block_stats.cache.total.value != io_size.value:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' is "
                f"{stats.block_stats.cache.total.value}, "
                f"should equal IO size: {io_size.value}\n")
        if stats_perc.block_stats.cache.total != 100:
            TestRun.LOGGER.error(
                f"{fail_message} 'Cache total' percentage is "
                f"{stats_perc.block_stats.cache.total}, "
                f"should equal 100\n")


def validate_error_stats(stats, stats_perc, cache_mode, fail_message):
    fail_message += f"in 'error' stats"
    for stat_name, stat_value in stats.items():
        if stat_value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} '{stat_name}' is {stat_value}, should equal 0\n")
    for stat_name, stat_value in stats_perc.items():
        if stat_value != 0:
            TestRun.LOGGER.error(
                f"{fail_message} '{stat_name}' percentage is {stat_value}, should equal 0\n")
