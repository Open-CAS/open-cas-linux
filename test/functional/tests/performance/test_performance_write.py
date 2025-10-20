#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
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
    set_wbt_lat,
    get_number_of_processors_from_cpuinfo,
    get_dut_cpu_physical_cores,
)
from type_def.size import Unit, Size


# TODO: for disks other than Intel Optane, fio ramp is needed before fio tests on raw disk
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "block_size", [Size(1, Unit.Blocks4096), Size(8, Unit.Blocks4096)]
)
@pytest.mark.parametrizex("queue_depth", [1, 16, 32])
def test_performance_write_insert_wb(block_size, queue_depth):
    """
    title: Test Open CAS performance for 100% write inserts scenario in write-back mode.
    description: |
        Compare write hit performance (throughput and latency) for Open CAS vs raw device
        for different start command options. Open CAS in Write-Back mode device should
        provide comparable throughput to bare cache device.
    pass_criteria:
      - passes performance threshold
    """

    processors_number = get_number_of_processors_from_cpuinfo()
    num_jobs = [int(processors_number / 2), processors_number]
    data_size = Size(20, Unit.GibiByte)
    cache_size = Size(24, Unit.GibiByte)
    cache_line_size = CacheLineSize.LINE_4KiB
    raw_disk_results = {}
    cas_results = {}

    fio_command = (
        Fio()
        .create_command()
        .direct()
        .read_write(ReadWrite.randrw)
        .write_percentage(100)
        .io_engine(IoEngine.libaio)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .cpus_allowed_policy(CpusAllowedPolicy.split)
        .run_time(timedelta(seconds=450))
        .block_size(block_size)
        .io_depth(queue_depth)
    )

    with TestRun.step("Prepare partitions for cache and core"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([cache_size])
        cache_part = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([data_size])
        core_part = core_device.partitions[0]

    with TestRun.step("Measure 4KiB write performance (throughput and latency) on raw disk."):
        fio_command.target(cache_part)
        for nj in num_jobs:
            # jobs directed to specific offsets
            offset = data_size.value // nj
            # round down offset to multiplication of 512 blocks
            offset = Size(offset // Unit.Blocks512.get_value() * Unit.Blocks512.get_value())
            fio_command.size(offset)
            for i in range(nj):
                job = fio_command.add_job(f"job{i + 1}")
                job.file_size((i + 1) * offset)
                job.offset(i * offset)

            raw_disk_results[nj] = fio_command.run().pop()
            TestRun.LOGGER.info(str(raw_disk_results[nj]))
            fio_command.clear_jobs()

    with TestRun.group("Measure read performance (throughput and latency) on CAS device"):
        for nj in num_jobs:
            TestRun.LOGGER.info(f"Measuring performance for num_jobs={nj}")

            with TestRun.step("Start cache and add core device"):
                cache = casadm.start_cache(
                    cache_part, CacheMode.WB, cache_line_size, cache_id=1, force=True
                )
                cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
                core = cache.add_core(core_part, core_id=1)

            with TestRun.step("Ensure that I/O scheduler for CAS device is 'none'"):
                TestRun.executor.run_expect_success(
                    f"sudo echo none > /sys/block/{core.path.lstrip('/dev/')}/queue/scheduler"
                )

            with TestRun.step("Run fio on CAS device"):
                fio_command.target(core)
                # jobs directed to specific offsets
                offset = data_size.value // nj
                # round down offset to multiplication of 512 blocks
                offset = Size(offset // Unit.Blocks512.get_value() * Unit.Blocks512.get_value())
                fio_command.size(offset)
                for i in range(nj):
                    job = fio_command.add_job(f"job{i + 1}")
                    job.file_size((i + 1) * offset)
                    job.offset(i * offset)
                cas_results[nj] = fio_command.run().pop()
                TestRun.LOGGER.info(str(cas_results[nj]))
                fio_command.clear_jobs()

            with TestRun.step("Check if write hits is equal to 0"):
                cache_stats = cache.get_statistics()
                write_hits = cache_stats.request_stats.write.hits
                if write_hits != 0:
                    TestRun.LOGGER.error(f"Write hits equal to: {write_hits}, expected: 0.")

            with TestRun.step("Stop cache"):
                cache.stop()

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
            TestRun.LOGGER.info(f"Write ratio: {write_iops_ratio}")

            if write_iops_ratio < 50:
                TestRun.LOGGER.error("The write iops ratio is below expected threshold (50%).")


@pytest.fixture(scope="session", autouse=True)
def disable_wbt_throttling():
    TestRun.LOGGER.info("Disabling write-back throttling for cache and core devices")
    set_wbt_lat(TestRun.disks["cache"], 0)
    set_wbt_lat(TestRun.disks["core"], 0)
