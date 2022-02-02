#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import random
from enum import Enum, auto

import pytest

from api.cas import casadm
from api.cas.cache_config import SeqCutOffPolicy, CacheMode, CacheLineSize
from api.cas.core import SEQ_CUTOFF_THRESHOLD_MAX
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, CpusAllowedPolicy
from test_utils.os_utils import Udev, sync, get_dut_cpu_physical_cores
from test_utils.size import Size, Unit


class VerifyType(Enum):
    NEGATIVE = auto()
    POSITIVE = auto()
    EQUAL = auto()


@pytest.mark.parametrize("thresholds_list", [[
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
]])
@pytest.mark.parametrize("cache_mode, io_type, io_type_last", [
    (CacheMode.WB, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WT, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WA, ReadWrite.read, ReadWrite.randread),
    (CacheMode.WO, ReadWrite.write, ReadWrite.randwrite)])
@pytest.mark.parametrizex("cls", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_multi_core(thresholds_list, cache_mode, io_type, io_type_last, cls):
    """
    title: Sequential cut-off tests during sequential and random IO 'always' policy with 4 cores
    description: |
        Testing if amount of data written to cache after sequential writes for different
        sequential cut-off thresholds on each core, while running sequential IO on 3 out of 4
        cores and random IO against the last core, is correct.
    pass_criteria:
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off threshold for three first cores.
        - Amount of written blocks to cache is equal to io size run against last core.
    """
    with TestRun.step(f"Test prepare (start cache (cache line size: {cls}) and add cores)"):
        cache, cores = prepare(cores_count=len(thresholds_list), cache_line_size=cls)
        writes_before = []
        io_sizes = []
        thresholds = []
        fio_additional_size = Size(10, Unit.Blocks4096)
        for i in range(len(thresholds_list)):
            thresholds.append(Size(thresholds_list[i], Unit.KibiByte))
            io_sizes.append((thresholds[i] + fio_additional_size).align_down(0x1000))

    with TestRun.step(f"Setting cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    for i, core in TestRun.iteration(enumerate(cores), "Set sequential cut-off parameters for "
                                                       "all cores"):
        with TestRun.step(f"Setting core sequential cut off policy to {SeqCutOffPolicy.always}"):
            core.set_seq_cutoff_policy(SeqCutOffPolicy.always)

        with TestRun.step(f"Setting core sequential cut off threshold to {thresholds[i]}"):
            core.set_seq_cutoff_threshold(thresholds[i])

    with TestRun.step("Creating FIO command (one job per core)"):
        block_size = Size(4, Unit.KibiByte)
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .block_size(block_size)
               .direct())

        # Run sequential IO against first three cores
        for i, core in enumerate(cores[:-1]):
            fio_job = fio.add_job(job_name=f"core_{core.core_id}")
            fio_job.size(io_sizes[i])
            fio_job.read_write(io_type)
            fio_job.target(core.path)
            writes_before.append(core.get_statistics().block_stats.cache.writes)

        # Run random IO against the last core
        fio_job = fio.add_job(job_name=f"core_{cores[-1].core_id}")
        fio_job.size(io_sizes[-1])
        fio_job.read_write(io_type_last)
        fio_job.target(cores[-1].path)
        writes_before.append(cores[-1].get_statistics().block_stats.cache.writes)

    with TestRun.step("Running IO against all cores"):
        fio.run()

    with TestRun.step("Verifying writes to cache count after IO"):
        margins = []
        for i, core in enumerate(cores[:-1]):
            promotion_count = core.get_seq_cut_off_parameters().promotion_count
            cutoff_threshold = thresholds[i]
            margins.append(min(block_size * (promotion_count - 1), cutoff_threshold))
        margin = sum(margins)

        for i, core in enumerate(cores[:-1]):
            verify_writes_count(core, writes_before[i], thresholds[i], io_sizes[i],
                                VerifyType.POSITIVE, io_margin=margin)

        verify_writes_count(cores[-1], writes_before[-1], thresholds[-1], io_sizes[-1],
                            VerifyType.EQUAL)


@pytest.mark.parametrize("thresholds_list", [[
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))),
]])
@pytest.mark.parametrize("cache_mode, io_type, io_type_last", [
    (CacheMode.WB, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WT, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WA, ReadWrite.read, ReadWrite.randread),
    (CacheMode.WO, ReadWrite.write, ReadWrite.randwrite)])
@pytest.mark.parametrizex("cls", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_multi_core_io_pinned(thresholds_list, cache_mode, io_type, io_type_last, cls):
    """
    title: Sequential cut-off tests during sequential and random IO 'always' policy with 4 cores
    description: |
        Testing if amount of data written to cache after sequential writes for different
        sequential cut-off thresholds on each core, while running sequential IO, pinned,
        on 3 out of 4 cores and random IO against the last core, is correct.
    pass_criteria:
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off threshold for three first cores.
        - Amount of written blocks to cache is equal to io size run against last core.
    """
    with TestRun.step(f"Test prepare (start cache (cache line size: {cls}) and add cores)"):
        cache, cores = prepare(cores_count=len(thresholds_list), cache_line_size=cls)
        writes_before = []
        io_sizes = []
        thresholds = []
        fio_additional_size = Size(10, Unit.Blocks4096)
        for i in range(len(thresholds_list)):
            thresholds.append(Size(thresholds_list[i], Unit.KibiByte))
            io_sizes.append((thresholds[i] + fio_additional_size).align_down(0x1000))

    with TestRun.step(f"Setting cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    for i, core in TestRun.iteration(enumerate(cores), "Set sequential cut-off parameters for "
                                                       "all cores"):
        with TestRun.step(f"Setting core sequential cut off policy to {SeqCutOffPolicy.always}"):
            core.set_seq_cutoff_policy(SeqCutOffPolicy.always)

        with TestRun.step(f"Setting core sequential cut off threshold to {thresholds[i]}"):
            core.set_seq_cutoff_threshold(thresholds[i])

    with TestRun.step("Creating FIO command (one job per core)"):
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .block_size(Size(1, Unit.Blocks4096))
               .direct()
               .cpus_allowed(get_dut_cpu_physical_cores())
               .cpus_allowed_policy(CpusAllowedPolicy.split))

        # Run sequential IO against first three cores
        for i, core in enumerate(cores[:-1]):
            fio_job = fio.add_job(job_name=f"core_{core.core_id}")
            fio_job.size(io_sizes[i])
            fio_job.read_write(io_type)
            fio_job.target(core.path)
            writes_before.append(core.get_statistics().block_stats.cache.writes)

        # Run random IO against the last core
        fio_job = fio.add_job(job_name=f"core_{cores[-1].core_id}")
        fio_job.size(io_sizes[-1])
        fio_job.read_write(io_type_last)
        fio_job.target(cores[-1].path)
        writes_before.append(cores[-1].get_statistics().block_stats.cache.writes)

    with TestRun.step("Running IO against all cores"):
        fio.run()

    with TestRun.step("Verifying writes to cache count after IO"):
        for i, core in enumerate(cores[:-1]):
            verify_writes_count(core, writes_before[i], thresholds[i], io_sizes[i],
                                VerifyType.POSITIVE)

        verify_writes_count(cores[-1], writes_before[-1], thresholds[-1], io_sizes[-1],
                            VerifyType.EQUAL)


@pytest.mark.parametrize("threshold_param", [
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte)))
])
@pytest.mark.parametrize("policy, verify_type", [(SeqCutOffPolicy.never, VerifyType.NEGATIVE),
                                                 (SeqCutOffPolicy.always, VerifyType.POSITIVE),
                                                 (SeqCutOffPolicy.full, VerifyType.NEGATIVE)])
@pytest.mark.parametrizex("cls", CacheLineSize)
@pytest.mark.parametrizex("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh(threshold_param, cls, io_dir, policy, verify_type):
    """
    title: Sequential cut-off tests for writes and reads for 'never', 'always' and 'full' policies
    description: |
        Testing if amount of data written to cache after sequential writes and reads for different
        sequential cut-off policies with cache configured with different cache line size
        is valid for sequential cut-off threshold parameter, assuming that cache occupancy
        doesn't reach 100% during test.
    pass_criteria:
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off parameter in case of 'always' policy.
        - Amount of written blocks to cache is at least equal io size in case of 'never' and 'full'
          policy.
    """
    with TestRun.step(f"Test prepare (start cache (cache line size: {cls}) and add cores)"):
        cache, cores = prepare(cores_count=1, cache_line_size=cls)
        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size(threshold_param, Unit.KibiByte)
        io_size = (threshold + fio_additional_size).align_down(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to {policy}"):
        cache.set_seq_cutoff_policy(policy)

    with TestRun.step(f"Setting cache sequential cut off policy threshold to "
                      f"{threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step(f"Running sequential IO ({io_dir})"):
        sync()
        writes_before = cores[0].get_statistics().block_stats.cache.writes
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(io_size)
              .read_write(io_dir)
              .target(f"{cores[0].path}")
              .direct()
         ).run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(cores[0], writes_before, threshold, io_size, verify_type)


@pytest.mark.parametrize("threshold_param", [
    random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte)))
])
@pytest.mark.parametrizex("cls", CacheLineSize)
@pytest.mark.parametrizex("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh_fill(threshold_param, cls, io_dir):
    """
    title: Sequential cut-off tests during writes and reads on full cache for 'full' policy
    description: |
        Testing if amount of data written to cache after sequential io against fully occupied
        cache for 'full' sequential cut-off policy with cache configured with different cache
        line sizes is valid for sequential cut-off threshold parameter.
    pass_criteria:
        - Amount of written blocks to cache is big enough to fill cache when 'never' sequential
          cut-off policy is set
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off parameter in case of 'full' policy.
    """
    with TestRun.step(f"Test prepare (start cache (cache line size: {cls}) and add cores)"):
        cache, cores = prepare(cores_count=1, cache_line_size=cls)
        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size(threshold_param, Unit.KibiByte)
        io_size = (threshold + fio_additional_size).align_down(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to "
                      f"{SeqCutOffPolicy.never}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Filling cache (sequential writes IO with size of cache device)"):
        sync()
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(cache.cache_device.size)
              .read_write(io_dir)
              .target(f"{cores[0].path}")
              .direct()
         ).run()

    with TestRun.step("Check if cache is filled enough (expecting occupancy not less than "
                      "95%)"):
        occupancy = cache.get_statistics(percentage_val=True).usage_stats.occupancy
        if occupancy < 95:
            TestRun.fail(f"Cache occupancy is too small: {occupancy}, expected at least 95%")

    with TestRun.step(f"Setting cache sequential cut off policy mode to "
                      f"{SeqCutOffPolicy.full}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.full)
    with TestRun.step(f"Setting cache sequential cut off policy threshold to "
                      f"{threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step(f"Running sequential IO ({io_dir})"):
        sync()
        writes_before = cores[0].get_statistics().block_stats.cache.writes
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(io_size)
              .read_write(io_dir)
              .target(f"{cores[0].path}")
              .direct()
         ).run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(cores[0], writes_before, threshold, io_size, VerifyType.POSITIVE)


def verify_writes_count(core, writes_before, threshold, io_size, ver_type=VerifyType.NEGATIVE,
                        io_margin=Size(8, Unit.KibiByte)):
    writes_after = core.get_statistics().block_stats.cache.writes
    writes_difference = writes_after - writes_before

    if ver_type is VerifyType.NEGATIVE:
        if writes_difference < io_size:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected at least "
                         f"{io_size}")
    elif ver_type is VerifyType.POSITIVE:
        if writes_difference >= threshold + io_margin:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected at most "
                         f"{threshold + io_margin}")
    elif ver_type is VerifyType.EQUAL:
        if writes_difference != io_size:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected {io_size}")


def prepare(cores_count=1, cache_line_size: CacheLineSize = None):
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']
    cache_device.create_partitions(
        [(SEQ_CUTOFF_THRESHOLD_MAX * cores_count + Size(5, Unit.GibiByte)).align_down(0x1000)])
    partitions = \
        [(SEQ_CUTOFF_THRESHOLD_MAX + Size(10, Unit.GibiByte)).align_down(0x1000)] * cores_count
    core_device.create_partitions(partitions)
    cache_part = cache_device.partitions[0]
    core_parts = core_device.partitions
    TestRun.LOGGER.info("Starting cache")

    cache = casadm.start_cache(cache_part, force=True, cache_line_size=cache_line_size)
    Udev.disable()
    TestRun.LOGGER.info("Adding core devices")
    core_list = []
    for core_part in core_parts:
        core_list.append(cache.add_core(core_dev=core_part))
    return cache, core_list
