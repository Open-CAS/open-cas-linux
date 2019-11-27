#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import pytest
import random
from enum import Enum, auto
from api.cas import casadm
from api.cas.core import SEQ_CUTOFF_THRESHOLD_MAX
from api.cas.cache_config import SeqCutOffPolicy, CacheMode
from api.cas.casadm import StatsFilter
from core.test_run import TestRun

from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit
from test_utils.os_utils import Udev, sync
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine


class VerifyType(Enum):
    NEGATIVE = auto()
    POSITIVE = auto()
    EQUAL = auto()


@pytest.mark.parametrize("cache_mode, io_type, io_type_last", [
    (CacheMode.WB, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WT, ReadWrite.write, ReadWrite.randwrite),
    (CacheMode.WA, ReadWrite.read, ReadWrite.randread),
    (CacheMode.WO, ReadWrite.write, ReadWrite.randwrite)])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_multi_core(cache_mode, io_type, io_type_last):
    """
    title: Sequential cut-off tests during sequential and random IO 'always' policy with 4 cores
    description: |
        Testing if amount of data written to cache after sequential writes for different
        sequential cut-off thresholds on each core while running sequential IO on 3 out of 4
        cores and random IO against the last core.
    pass_criteria:
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off threshold for three first cores.
        - Amount of written blocks to cache is equal to io size run against last core.
    """
    with TestRun.step("Test prepare (start cache and add cores)"):
        cache, cores = prepare(cores_count=4)
        writes_before = []
        io_sizes = []
        thresholds = []
        for x in range(4):
            thresholds.append(Size(random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX))))

    with TestRun.step(f"Setting cache mode to {cache_mode}"):
        cache.set_cache_mode(cache_mode)

    for i, core in TestRun.iteration(enumerate(cores), "Set sequential cut-off parameters for "
                                                       "all cores"):
        with TestRun.step(f"Setting core sequential cut off policy to {SeqCutOffPolicy.always}"):
            core.set_seq_cutoff_policy(SeqCutOffPolicy.always)

        with TestRun.step(f"Setting core sequential cut off threshold to {thresholds[i]}"):
            core.set_seq_cutoff_threshold(thresholds[i])

    with TestRun.group("Preparing FIO configuration"):
        fio_additional_size = Size(10, Unit.Blocks4096)
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .direct())

        # Run sequential IO against first three cores
        for i, core in TestRun.iteration(enumerate(cores[:-1])):
            io_sizes.append((thresholds[i] + fio_additional_size).align(0x1000))
            fio_job = fio.add_job(job_name=f"core_{core.core_id}")
            fio_job.size(io_sizes[i])
            fio_job.read_write(io_type)
            fio_job.target(core.system_path)
            writes_before.append(core.get_core_statistics(
                stat_filter=[StatsFilter.blk])["writes to cache"])

        # Run random IO against the last core
        io_sizes.append((thresholds[-1] + fio_additional_size).align(0x1000))
        fio_job = fio.add_job(job_name=f"core_{cores[-1].core_id}")
        fio_job.size(io_sizes[-1])
        fio_job.read_write(io_type_last)
        fio_job.target(cores[-1].system_path)
        writes_before.append(cores[-1].get_core_statistics(stat_filter=[StatsFilter.blk])[
                             "writes to cache"])

    with TestRun.step("Running IO against all cores"):
        fio.run()

    with TestRun.step("Verifying writes to cache count after IO"):
        for i, core in TestRun.iteration(enumerate(cores[:-1])):
            verify_writes_count(core, writes_before[i], thresholds[i], io_sizes[i],
                                VerifyType.POSITIVE)

        verify_writes_count(cores[-1], writes_before[-1], thresholds[-1], io_sizes[-1],
                            VerifyType.EQUAL)


@pytest.mark.parametrize("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.parametrize("policy, negative", [(SeqCutOffPolicy.never, VerifyType.NEGATIVE),
                                              (SeqCutOffPolicy.always,VerifyType.POSITIVE),
                                              (SeqCutOffPolicy.full, VerifyType.NEGATIVE)])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh(io_dir, policy, negative):
    """
    title: Sequential cut-off tests during writes and read for 'never', 'always' and 'full' policies
    description: |
        Testing if amount of data written to cache after sequential writes for different
        sequential cut-off policies with cache configured with different cache line size
        is valid for sequential cut-off threshold parameter, assuming that cache occupancy
        doesn't reach 100% during test.
    pass_criteria:
        - Amount of written blocks to cache is less or equal than amount set
          with sequential cut-off parameter in case of 'always' policy.
        - Amount of written blocks to cache is at least equal io size in case of 'never' and 'full'
          policy.
    """
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()
        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size(random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX)))
        io_size = (threshold + fio_additional_size).align(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to {policy}"):
        cache.set_seq_cutoff_policy(policy)

    with TestRun.step(f"Setting cache sequential cut off policy threshold to "
                      f"{threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step(f"Running sequential IO ({io_dir})"):
        sync()
        writes_before = cores[0].get_core_statistics(
            stat_filter=[StatsFilter.blk])["writes to cache"]
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(io_size)
              .read_write(io_dir)
              .target(f"{cores[0].system_path}")
              .direct()
         ).run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(cores[0], writes_before, threshold, io_size, negative)


@pytest.mark.parametrize("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh_fill(io_dir):
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
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()
        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size(random.randint(1, int(SEQ_CUTOFF_THRESHOLD_MAX)))
        io_size = (threshold + fio_additional_size).align(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to "
                      f"{SeqCutOffPolicy.never}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Filling cache (sequential writes IO with size of cache device)"):
        sync()
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(cache.cache_device.size)
              .read_write(io_dir)
              .target(f"{cores[0].system_path}")
              .direct()
         ).run()

    with TestRun.step("Check if cache is filled enough (expecting occupancy not less than "
                      "95%)"):
        occupancy = cache.get_cache_statistics(stat_filter=[StatsFilter.usage],
                                               percentage_val=True)["occupancy"]
        if occupancy < 95:
            TestRun.fail(f"Cache occupancy is too small: {occupancy}, expected at least 95%")

    with TestRun.step(f"Setting cache sequenggtial cut off policy mode to "
                      f"{SeqCutOffPolicy.full}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.full)
    with TestRun.step(f"Setting cache sequential cut off policy threshold to "
                      f"{threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step(f"Running sequential IO ({io_dir})"):
        sync()
        writes_before = cores[0].get_core_statistics(
            stat_filter=[StatsFilter.blk])["writes to cache"]
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(io_size)
              .read_write(io_dir)
              .target(f"{cores[0].system_path}")
              .direct()
         ).run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(cores[0], writes_before, threshold, io_size)


def verify_writes_count(core, writes_before, threshold, io_size, ver_type=VerifyType.NEGATIVE):
    writes_after = core.get_core_statistics(stat_filter=[StatsFilter.blk])["writes to cache"]
    writes_difference = writes_after - writes_before

    if ver_type is VerifyType.NEGATIVE:
        if writes_difference < io_size:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected at least "
                         f"{io_size}")
    elif ver_type is VerifyType.POSITIVE:
        io_margin = Size(8, Unit.KibiByte)
        if writes_difference >= threshold + io_margin:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected at most "
                         f"{threshold + io_margin}")
    elif ver_type is VerifyType.EQUAL:
        if writes_difference != io_size:
            TestRun.fail(f"Wrong writes count: {writes_difference} , expected {io_size}")


def prepare(cores_count=1):
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']
    cache_device.create_partitions([SEQ_CUTOFF_THRESHOLD_MAX + Size(1, Unit.GibiByte)])
    partitions = [SEQ_CUTOFF_THRESHOLD_MAX + Size(5, Unit.GibiByte)] * cores_count
    core_device.create_partitions(partitions)
    cache_part = cache_device.partitions[0]
    core_parts = core_device.partitions
    TestRun.LOGGER.info("Staring cache")

    cache = casadm.start_cache(cache_part, force=True)
    Udev.disable()
    TestRun.LOGGER.info("Adding core devices")
    core_list = []
    for core_part in core_parts:
        core_list.append(cache.add_core(core_dev=core_part))
    return cache, core_list
