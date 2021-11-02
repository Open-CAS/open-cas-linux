#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    SeqCutOffPolicy,
    CleaningPolicy,
)
from utils.performance import WorkloadParameter
from core.test_run import TestRun
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import Udev, set_wbt_lat, get_dut_cpu_physical_cores
from test_utils.size import Size, Unit
from test_utils.output import CmdException
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType


@pytest.mark.performance()
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("queue_depth", [1, 4, 16, 64, 256])
@pytest.mark.parametrize("numjobs", [1, 4, 16, 64, 256])
@pytest.mark.parametrize("cache_line_size", CacheLineSize)
def test_4k_100p_hit_reads_wt(queue_depth, numjobs, cache_line_size, perf_collector, request):
    """
        title: Test CAS performance in 100% Cache Hit scenario
        description: |
          Characterize cache device with workload (parametrized by qd and job number), and then run
          the same workload on cached volume.
        pass_criteria:
          - always passes
    """
    TESTING_WORKSET = Size(20, Unit.GiB)

    fio_cfg = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .block_size(Size(4, Unit.KiB))
        .read_write(ReadWrite.randread)
        .io_depth(queue_depth)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .direct()
    )

    with TestRun.step("Characterize cache device"):
        cache_dev_characteristics = characterize_cache_device(
            request.node.name, fio_cfg, queue_depth, numjobs, TESTING_WORKSET
        )
    fio_cfg.clear_jobs()

    with TestRun.step("Prepare cache and core"):
        cache, core = prepare_config(cache_line_size, CacheMode.WT)

    fio_cfg = fio_cfg.target(core)
    spread_jobs(fio_cfg, numjobs, TESTING_WORKSET)

    with TestRun.step("Fill the cache"):
        prefill_cache(core, TESTING_WORKSET)

    with TestRun.step("Run fio"):
        cache_results = fio_cfg.run()[0]

    perf_collector.insert_workload_param(numjobs, WorkloadParameter.NUM_JOBS)
    perf_collector.insert_workload_param(queue_depth, WorkloadParameter.QUEUE_DEPTH)
    perf_collector.insert_cache_metrics_from_fio_job(cache_dev_characteristics)
    perf_collector.insert_exp_obj_metrics_from_fio_job(cache_results)
    perf_collector.insert_config_from_cache(cache)


def prefill_cache(core, size):
    (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .block_size(Size(4, Unit.KiB))
        .read_write(ReadWrite.write)
        .target(core)
        .size(size)
        .direct()
        .run()
    )


@pytest.fixture(scope="session", autouse=True)
def disable_wbt_throttling():
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    try:
        set_wbt_lat(cache_device, 0)
    except CmdException:
        TestRun.LOGGER.warning("Couldn't disable write-back throttling for cache device")
    try:
        set_wbt_lat(core_device, 0)
    except CmdException:
        TestRun.LOGGER.warning("Couldn't disable write-back throttling for core device")


def prepare_config(cache_line_size, cache_mode):
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    core_device.create_partitions([Size(3, Unit.GiB)])

    cache = casadm.start_cache(
        cache_device, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True,
    )
    cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    cache.set_cleaning_policy(CleaningPolicy.nop)

    Udev.disable()

    core = cache.add_core(core_device.partitions[0])

    return cache, core


def spread_jobs(fio_cfg, numjobs, size):
    offset = (size / numjobs).align_down(Unit.Blocks512.value)

    for i in range(numjobs):
        fio_cfg.add_job(f"job_{i+1}").offset(offset * i).size(offset * (i + 1))


def characterize_cache_device(test_name, fio_cfg, queue_depth, numjobs, size):
    cache_device = TestRun.disks["cache"]

    try:
        return TestRun.dev_characteristics[test_name][queue_depth][numjobs]
    except AttributeError:
        pass
    except KeyError:
        pass

    spread_jobs(fio_cfg, numjobs, size)
    result = fio_cfg.target(cache_device).run()[0]

    if not hasattr(TestRun, "dev_characteristics"):
        TestRun.dev_characteristics = {}
    if test_name not in TestRun.dev_characteristics:
        TestRun.dev_characteristics[test_name] = {}
    if queue_depth not in TestRun.dev_characteristics[test_name]:
        TestRun.dev_characteristics[test_name][queue_depth] = {}

    TestRun.dev_characteristics[test_name][queue_depth][numjobs] = result

    return result
