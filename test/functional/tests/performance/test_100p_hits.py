#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
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
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import Udev, set_wbt_lat, get_dut_cpu_physical_cores
from connection.utils.output import CmdException
from types.size import Size, Unit
from utils.performance import WorkloadParameter


@pytest.mark.os_dependent
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

    testing_range = Size(3, Unit.GiB)
    testing_workset = Size(20, Unit.GiB)
    size_per_job = testing_workset / numjobs

    fio_cfg = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .block_size(Size(4, Unit.KiB))
        .read_write(ReadWrite.randread)
        .io_depth(queue_depth)
        .cpus_allowed(get_dut_cpu_physical_cores())
        .direct()
        .io_size(size_per_job)
    )
    # spread jobs
    offset = (testing_range / numjobs).align_down(Unit.Blocks512.value)
    for i in range(numjobs):
        fio_cfg.add_job(f"job_{i+1}").offset(offset * i).size(offset * (i + 1))

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([testing_range + Size(1, Unit.GiB)])
        cache_device = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([testing_range])
        core_device = core_device.partitions[0]

    with TestRun.step("Characterize cache device"):
        cache_dev_characteristics = characterize_cache_device(
            request.node.name, fio_cfg, queue_depth, numjobs, cache_device
        )

    with TestRun.step("Configure cache and add core"):
        cache = casadm.start_cache(
            cache_device,
            cache_mode=CacheMode.WT,
            cache_line_size=cache_line_size,
            force=True,
        )
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

        core = cache.add_core(core_device)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Prefill cache"):
        prefill_cache(core)

    with TestRun.step("Run workload on the exported object"):
        fio_cfg = fio_cfg.target(core)
        cache_results = fio_cfg.run()[0]

    perf_collector.insert_workload_param(numjobs, WorkloadParameter.NUM_JOBS)
    perf_collector.insert_workload_param(queue_depth, WorkloadParameter.QUEUE_DEPTH)
    perf_collector.insert_cache_metrics_from_fio_job(cache_dev_characteristics)
    perf_collector.insert_exp_obj_metrics_from_fio_job(cache_results)
    perf_collector.insert_config_from_cache(cache)


def prefill_cache(core):
    (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .block_size(Size(4, Unit.KiB))
        .read_write(ReadWrite.write)
        .target(core)
        .size(core.size)
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


def characterize_cache_device(test_name, fio_cfg, queue_depth, numjobs, cache_device):
    try:
        return TestRun.dev_characteristics[test_name][queue_depth][numjobs]
    except AttributeError:
        pass
    except KeyError:
        pass

    result = fio_cfg.target(cache_device).run()[0]

    if not hasattr(TestRun, "dev_characteristics"):
        TestRun.dev_characteristics = {}
    if test_name not in TestRun.dev_characteristics:
        TestRun.dev_characteristics[test_name] = {}
    if queue_depth not in TestRun.dev_characteristics[test_name]:
        TestRun.dev_characteristics[test_name][queue_depth] = {}

    TestRun.dev_characteristics[test_name][queue_depth][numjobs] = result

    return result
