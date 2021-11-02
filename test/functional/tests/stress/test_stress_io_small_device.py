#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from datetime import timedelta

from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheLineSize, CacheMode, CleaningPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import CpusAllowedPolicy, IoEngine, ReadWrite
from test_utils.size import Size, Unit

stress_time = timedelta(minutes=30)


@pytest.mark.parametrize("cores_number", [1, 4])
@pytest.mark.parametrize("cache_config", [(CacheMode.WT, None),
                                          (CacheMode.WA, None),
                                          (CacheMode.PT, None),
                                          (CacheMode.WB, CleaningPolicy.acp),
                                          (CacheMode.WB, CleaningPolicy.alru),
                                          (CacheMode.WB, CleaningPolicy.nop),
                                          (CacheMode.WO, CleaningPolicy.acp),
                                          (CacheMode.WO, CleaningPolicy.alru),
                                          (CacheMode.WO, CleaningPolicy.nop)])
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_small_cas_device(cache_line_size, cores_number, cache_config):
    """
        title: Stress test for verifying data on small CAS devices.
        description: |
          Validate the ability of CAS to handle many iops when device is small
          using different cache modes, cache line sizes and core numbers.
        pass_criteria:
          - No system crash.
          - Md5 sums of core device and exported object are equal.
    """
    cache_mode, cleaning_policy = cache_config

    with TestRun.step(f"Prepare 1 cache and {cores_number} core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(100, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_sizes = [Size(200, Unit.MebiByte)] * cores_number
        core_dev.create_partitions(core_sizes)

    with TestRun.step(f"Start cache with {cores_number} cores."):
        cache = casadm.start_cache(cache_part, cache_mode, cache_line_size, force=True)
        cores = []
        for i in range(cores_number):
            cores.append(cache.add_core(core_dev.partitions[i]))
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != cores_number:
            TestRun.fail(
                f"Expected cores count: {cores_number}; Actual cores count: {cores_count}.")

    if cleaning_policy is not None:
        with TestRun.step("Set cleaning policy."):
            cache.set_cleaning_policy(cleaning_policy)

    with TestRun.step(f"Stress cache for {int(stress_time.total_seconds() / 60)} minutes."):
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .io_depth(128)
               .direct()
               .time_based()
               .run_time(stress_time)
               .read_write(ReadWrite.randrw)
               .block_size(cache_line_size)
               .num_jobs(cores_number)
               .cpus_allowed_policy(CpusAllowedPolicy.split))
        for core in cores:
            fio.add_job(f"job_{core.core_id}").target(core.path)
        output = fio.run()[0]
        TestRun.LOGGER.info(f"Total read I/O [KiB]: {str(output.read_io())}\n"
                            f"Total write I/O [KiB]: {str(output.write_io())}")

    with TestRun.step("Count md5 sum for exported objects"):
        md5sum_core = []
        for core in cores:
            md5sum_core.append(TestRun.executor.run(
                f"md5sum -b {core.path}").stdout.split(" ")[0])

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Count md5 sum for core devices"):
        md5sum_core_dev = []
        for core_dev in core_dev.partitions:
            md5sum_core_dev.append(TestRun.executor.run(
                f"md5sum -b {core_dev.path}").stdout.split(" ")[0])

    with TestRun.step("Compare md5 sum of exported objects and cores."):
        if md5sum_core_dev != md5sum_core:
            TestRun.LOGGER.error(f"Md5 sums of core devices and of exported objects are different.")

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()
