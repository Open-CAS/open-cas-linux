#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from datetime import timedelta
from api.cas import casadm
from api.cas.cache_config import CacheLineSize, CacheMode, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, CpusAllowedPolicy
from test_tools.os_tools import (
    get_number_of_processors_from_cpuinfo,
    set_wbt_lat,
    get_dut_cpu_physical_cores,
)
from type_def.size import Unit, Size


def fill_cas_cache(target, bs):
    (
        Fio()
        .create_command()
        .target(target)
        .direct()
        .num_jobs(1)
        .read_write(ReadWrite.read)
        .io_engine(IoEngine.libaio)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .cpus_allowed_policy(CpusAllowedPolicy.split)
        .block_size(bs)
        .io_depth(32)
        .file_size(target.size)
        .run()
    )


# TODO: for disks other than Intel Optane, fio ramp is needed before fio tests on raw disk
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "block_size", [Size(1, Unit.Blocks4096), Size(8, Unit.Blocks4096)]
)
@pytest.mark.parametrizex("queue_depth", [1, 16, 32])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_performance_read_hit_wt(cache_line_size, block_size, queue_depth):
    """
    title: Test CAS reads performance for write-through mode.
    description: |
        Compare read hit performance (throughput and latency) for Open CAS vs raw device
        for different start command options.Open CAS in Write-Through mode device should
        provide comparable throughput to bare cache device.
    pass_criteria:
      - passes performance threshold
    """

    processors_number = get_number_of_processors_from_cpuinfo()
    num_jobs = [int(processors_number / 2), processors_number]
    data_size = Size(20, Unit.GibiByte)
    cache_size = Size(24, Unit.GibiByte)

    fio_command = (
        Fio()
        .create_command()
        .direct()
        .read_write(ReadWrite.randread)
        .io_engine(IoEngine.libaio)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .cpus_allowed_policy(CpusAllowedPolicy.split)
        .block_size(block_size)
        .io_depth(queue_depth)
        .file_size(data_size)
        .run_time(timedelta(seconds=450))
    )

    with TestRun.step("Prepare partitions for cache and core"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([cache_size])
        cache_part = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([data_size])
        core_part = core_device.partitions[0]

    with TestRun.step("Measure read performance (throughput and latency) on raw disk."):
        fio_command.target(cache_part)
        raw_disk_results = {}

        for nj in num_jobs:
            fio_command.num_jobs(nj)
            raw_disk_results[nj] = fio_command.run().pop()
            TestRun.LOGGER.info(str(raw_disk_results[nj]))

    with TestRun.step("Start cache and add core device"):
        cache = casadm.start_cache(
            cache_part, CacheMode.WT, cache_line_size, cache_id=1, force=True
        )
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        core = cache.add_core(core_part, core_id=1)

    with TestRun.step("Ensure that I/O scheduler for CAS device is 'none'"):
        TestRun.executor.run_expect_success(
            f"sudo echo none > /sys/block/{core.path.lstrip('/dev/')}/queue/scheduler"
        )

    with TestRun.step("Fill the cache with data via CAS device"):
        fill_cas_cache(core, cache_line_size)
        casadm.reset_counters(1, 1)

    with TestRun.step("Measure read performance (throughput and latency) on CAS device"):
        fio_command.target(core)
        cas_results = {}

        for nj in num_jobs:
            fio_command.num_jobs(nj)
            cas_results[nj] = fio_command.run().pop()
            TestRun.LOGGER.info(str(cas_results[nj]))

    with TestRun.step("Check if read hit percentage during fio is greater or equal to 99"):
        cache_stats = cache.get_statistics()
        read_hits = cache_stats.request_stats.read.hits
        read_total = cache_stats.request_stats.read.total
        read_hits_percentage = read_hits / read_total * 100
        if read_hits_percentage <= 99:
            TestRun.LOGGER.error(
                f"Read hits percentage too low: {read_hits_percentage}%\n"
                f"Read hits: {read_hits}, read total: {read_total}"
            )

    with TestRun.step("Compare fio results"):
        for nj in num_jobs:
            cas_latency = cas_results[nj].read_completion_latency_average().microseconds
            raw_disk_latency = raw_disk_results[nj].read_completion_latency_average().microseconds
            cas_read_iops = cas_results[nj].read_iops()
            raw_disk_iops = raw_disk_results[nj].read_iops()
            read_iops_ratio = (100 * cas_read_iops) / raw_disk_iops

            TestRun.LOGGER.info(
                f"Results for num_jobs={nj}, queue_depth={queue_depth},"
                f" block_size={block_size}, cache_line_size={cache_line_size}"
            )
            TestRun.LOGGER.info("Average read latency (us):")
            TestRun.LOGGER.info(f" - (raw disk) {raw_disk_latency}")
            TestRun.LOGGER.info(f" - (CAS device) {cas_latency}")
            TestRun.LOGGER.info("Average read throughput (IOPS):")
            TestRun.LOGGER.info(f" - (raw disk) {raw_disk_iops}")
            TestRun.LOGGER.info(f" - (CAS device) {cas_read_iops}")
            TestRun.LOGGER.info(f"Read ratio: {read_iops_ratio}")

            if read_iops_ratio < 85:
                TestRun.LOGGER.error(f"The read iops ratio is below expected threshold (85%).")


# TODO: for disks other than Intel Optane, fio ramp is needed before fio tests on raw disk
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "block_size", [Size(1, Unit.Blocks4096), Size(8, Unit.Blocks4096)]
)
@pytest.mark.parametrizex("queue_depth", [1, 16, 32])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
def test_performance_read_hit_wb(cache_line_size, block_size, queue_depth):
    """
    title: Test CAS read/write hit performance for write-back mode.
    description: |
        Compare read/write hit performance (throughput and latency)
        for Open CAS vs raw device. Open CAS in Write-Back mode device
        should provide comparable throughput to bare cache device.
    pass_criteria:
      - passes performance threshold
    """
    processors_number = get_number_of_processors_from_cpuinfo()
    num_jobs = [int(processors_number / 2), processors_number]
    data_size = Size(20, Unit.GibiByte)
    cache_size = Size(24, Unit.GibiByte)

    fio_command = (
        Fio()
        .create_command()
        .direct()
        .read_write(ReadWrite.randrw)
        .write_percentage(30)
        .io_engine(IoEngine.libaio)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .cpus_allowed_policy(CpusAllowedPolicy.split)
        .block_size(block_size)
        .io_depth(queue_depth)
        .file_size(data_size)
        .run_time(timedelta(seconds=450))
    )

    with TestRun.step("Prepare partitions for cache and core"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([cache_size])
        cache_part = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([data_size])
        core_part = core_device.partitions[0]

    with TestRun.step("Measure read/write performance (throughput and latency) on raw disk."):
        fio_command.target(cache_part)
        raw_disk_results = {}

        for nj in num_jobs:
            fio_command.num_jobs(nj)
            raw_disk_results[nj] = fio_command.run().pop()
            TestRun.LOGGER.info(str(raw_disk_results[nj]))

    with TestRun.step("Start cache and add core device"):
        cache = casadm.start_cache(cache_part, CacheMode.WB, cache_line_size, cache_id=1)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        core = cache.add_core(core_part, core_id=1)

    with TestRun.step("Ensure that I/O scheduler for CAS device is 'none'"):
        TestRun.executor.run_expect_success("sudo echo none > /sys/block/cas1-1/queue/scheduler")

    with TestRun.step("Fill the cache with data via CAS device"):
        # TODO add Device.fill_with_data api ?
        fill_cas_cache(core, cache_line_size)
        casadm.reset_counters(1, 1)

    with TestRun.step("Measure read performance (throughput and latency) on CAS device"):
        fio_command.target(core)
        cas_results = {}

        for nj in num_jobs:
            fio_command.num_jobs(nj)
            cas_results[nj] = fio_command.run().pop()
            TestRun.LOGGER.info(str(cas_results[nj]))

    with TestRun.step("Check if hit percentage during fio is greater or equal to 99"):
        cache_stats = cache.get_statistics()
        hits = cache_stats.request_stats.read.hits + cache_stats.request_stats.write.hits
        total = cache_stats.request_stats.read.total + cache_stats.request_stats.write.total
        hits_percentage = hits / total * 100
        if hits_percentage <= 99:
            TestRun.LOGGER.error(
                f"Hits percentage too low: {hits_percentage}% (hits: {hits}, total: {total})"
            )

    with TestRun.step("Compare fio results"):
        for nj in num_jobs:
            cas_read_latency = cas_results[nj].read_completion_latency_average().microseconds
            cas_write_latency = cas_results[nj].write_completion_latency_average().microseconds
            disk_read_latency = raw_disk_results[nj].read_completion_latency_average().microseconds
            disk_write_latency = (
                raw_disk_results[nj].write_completion_latency_average().microseconds
            )

            cas_read_iops = cas_results[nj].read_iops()
            disk_read_iops = raw_disk_results[nj].read_iops()
            read_iops_ratio = (100 * cas_read_iops) / disk_read_iops

            cas_write_iops = cas_results[nj].write_iops()
            disk_write_iops = raw_disk_results[nj].write_iops()
            write_iops_ratio = (100 * cas_write_iops) / disk_write_iops

            TestRun.LOGGER.info(
                f"Results for num_jobs={nj}, queue_depth={queue_depth},"
                f" block_size={block_size}, cache_line_size={cache_line_size}"
            )
            TestRun.LOGGER.info("Average read/write latency (us):")
            TestRun.LOGGER.info(f" - (disk) {disk_read_latency}/{disk_write_latency}")
            TestRun.LOGGER.info(f" - (CAS) {cas_read_latency}/{cas_write_latency}")
            TestRun.LOGGER.info("Average read/write throughput (IOPS):")
            TestRun.LOGGER.info(f" - (disk) {disk_read_iops}/{raw_disk_results[nj].write_iops()}")
            TestRun.LOGGER.info(f" - (CAS) {cas_read_iops}/{cas_results[nj].write_iops()}")
            TestRun.LOGGER.info(f"Read ratio: {read_iops_ratio}")
            TestRun.LOGGER.info(f"Write ratio: {write_iops_ratio}")

            if read_iops_ratio < 90:
                TestRun.LOGGER.error(f"The read iops ratio is below expected threshold (90%).")

            if write_iops_ratio < 90:
                TestRun.LOGGER.error(f"The write iops ratio is below expected threshold (90%).")


@pytest.fixture(scope="session", autouse=True)
def disable_wbt_throttling():
    TestRun.LOGGER.info("Disabling write-back throttling for cache and core devices")
    set_wbt_lat(TestRun.disks["cache"], 0)
    set_wbt_lat(TestRun.disks["core"], 0)
