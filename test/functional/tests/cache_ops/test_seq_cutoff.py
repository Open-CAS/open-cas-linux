#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from enum import Enum, auto

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


@pytest.mark.parametrize(
    "cache_mode, io_type, io_type_last",
    [
        (CacheMode.WB, ReadWrite.write, ReadWrite.randwrite),
        (CacheMode.WT, ReadWrite.write, ReadWrite.randwrite),
        (CacheMode.WO, ReadWrite.write, ReadWrite.randwrite),
        (CacheMode.WA, ReadWrite.read, ReadWrite.randread),
    ],
)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_multi_core(cache_mode, io_type, io_type_last, cache_line_size):
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

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX * 4 + Size(value=5, unit=Unit.GibiByte))]
        )
        core_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX + Size(value=10, unit=Unit.GibiByte))] * 4
        )

        cache_part = cache_device.partitions[0]
        core_parts = core_device.partitions

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(
        f"Start cache in {cache_mode} mode and add {len(core_parts)} cores to the cache"
    ):
        cache = casadm.start_cache(
            cache_dev=cache_part, cache_mode=cache_mode, force=True, cache_line_size=cache_line_size
        )
        core_list = [cache.add_core(core_dev=core_part) for core_part in core_parts]

    with TestRun.step("Set sequential cut-off parameters for all cores"):
        writes_before_list = []
        fio_additional_size = Size(10, Unit.Blocks4096)
        thresholds_list = [
            Size.generate_random_size(
                min_size=1,
                max_size=SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte),
                unit=Unit.KibiByte,
            )
            for _ in core_list
        ]
        io_sizes_list = [
            (threshold_size + fio_additional_size).align_down(0x1000)
            for threshold_size in thresholds_list
        ]

        for core, threshold in zip(core_list, thresholds_list):
            core.set_seq_cutoff_policy(SeqCutOffPolicy.always)
            core.set_seq_cutoff_threshold(threshold)

    with TestRun.step("Prepare sequential IO against first three cores"):
        block_size = Size(4, Unit.KibiByte)
        fio = Fio().create_command().io_engine(IoEngine.libaio).block_size(block_size).direct(True)

        for core, io_size in zip(core_list[:-1], io_sizes_list[:-1]):
            fio_job = fio.add_job(f"core_{core.core_id}")
            fio_job.size(io_size)
            fio_job.read_write(io_type)
            fio_job.target(core.path)
            writes_before_list.append(core.get_statistics().block_stats.cache.writes)

    with TestRun.step("Prepare random IO against the last core"):
        fio_job = fio.add_job(f"core_{core_list[-1].core_id}")
        fio_job.size(io_sizes_list[-1])
        fio_job.read_write(io_type_last)
        fio_job.target(core_list[-1].path)
        writes_before_list.append(core_list[-1].get_statistics().block_stats.cache.writes)

    with TestRun.step("Run fio against all cores"):
        fio.run()

    with TestRun.step("Verify writes to cache count after IO"):
        margins = [
            min(block_size * (core.get_seq_cut_off_parameters().promotion_count - 1), threshold)
            for core, threshold in zip(core_list[:-1], thresholds_list[:-1])
        ]
        margin = Size.zero()
        for size in margins:
            margin += size

        for core, writes, threshold, io_size in zip(
            core_list[:-1], writes_before_list[:-1], thresholds_list[:-1], io_sizes_list[:-1]
        ):
            verify_writes_count(
                core=core,
                writes_before=writes,
                threshold=threshold,
                io_size=io_size,
                ver_type=VerifyType.POSITIVE,
                io_margin=margin,
            )

        verify_writes_count(
            core=core_list[-1],
            writes_before=writes_before_list[-1],
            threshold=thresholds_list[-1],
            io_size=io_sizes_list[-1],
            ver_type=VerifyType.EQUAL,
        )


@pytest.mark.parametrize(
    "cache_mode, io_type, io_type_last",
    [
        (CacheMode.WB, ReadWrite.write, ReadWrite.randwrite),
        (CacheMode.WT, ReadWrite.write, ReadWrite.randwrite),
        (CacheMode.WA, ReadWrite.read, ReadWrite.randread),
        (CacheMode.WO, ReadWrite.write, ReadWrite.randwrite),
    ],
)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_multi_core_io_pinned(cache_mode, io_type, io_type_last, cache_line_size):
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

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX * 4 + Size(value=5, unit=Unit.GibiByte))]
        )
        core_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX + Size(value=10, unit=Unit.GibiByte))] * 4
        )
        cache_part = cache_device.partitions[0]
        core_parts = core_device.partitions

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(
        f"Start cache in {cache_mode} mode and add {len(core_parts)} cores to the cache"
    ):
        cache = casadm.start_cache(
            cache_dev=cache_part,
            cache_mode=cache_mode,
            force=True,
            cache_line_size=cache_line_size,
        )
        core_list = [cache.add_core(core_dev=core_part) for core_part in core_parts]

    with TestRun.step(f"Set sequential cut-off parameters for all cores"):
        writes_before_list = []
        fio_additional_size = Size(10, Unit.Blocks4096)
        thresholds_list = [
            Size.generate_random_size(
                min_size=1,
                max_size=SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte),
                unit=Unit.KibiByte,
            )
            for _ in core_list
        ]
        io_sizes_list = [
            (threshold_size + fio_additional_size).align_down(0x1000)
            for threshold_size in thresholds_list
        ]

        for core, threshold in zip(core_list, thresholds_list):
            core.set_seq_cutoff_policy(SeqCutOffPolicy.always)
            core.set_seq_cutoff_threshold(threshold)

    with TestRun.step("Prepare sequential IO against first three cores"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(1, Unit.Blocks4096))
            .direct(True)
            .cpus_allowed(get_dut_cpu_physical_cores())
            .cpus_allowed_policy(CpusAllowedPolicy.split)
        )

        # Run sequential IO against first three cores
        for core, io_size in zip(core_list[:-1], io_sizes_list[:-1]):
            fio_job = fio.add_job(job_name=f"core_{core.core_id}")
            fio_job.size(io_size)
            fio_job.read_write(io_type)
            fio_job.target(core.path)
            writes_before_list.append(core.get_statistics().block_stats.cache.writes)

        # Run random IO against the last core
        fio_job = fio.add_job(job_name=f"core_{core_list[-1].core_id}")
        fio_job.size(io_sizes_list[-1])
        fio_job.read_write(io_type_last)
        fio_job.target(core_list[-1].path)
        writes_before_list.append(core_list[-1].get_statistics().block_stats.cache.writes)

    with TestRun.step("Running IO against all cores"):
        fio.run()

    with TestRun.step("Verifying writes to cache count after IO"):
        for core, writes, threshold, io_size in zip(
            core_list[:-1], writes_before_list[:-1], thresholds_list[:-1], io_sizes_list[:-1]
        ):
            verify_writes_count(
                core=core,
                writes_before=writes,
                threshold=threshold,
                io_size=io_size,
                ver_type=VerifyType.POSITIVE,
            )

        verify_writes_count(
            core=core_list[-1],
            writes_before=writes_before_list[-1],
            threshold=thresholds_list[-1],
            io_size=io_sizes_list[-1],
            ver_type=VerifyType.EQUAL,
        )


@pytest.mark.parametrize(
    "policy, verify_type",
    [
        (SeqCutOffPolicy.never, VerifyType.NEGATIVE),
        (SeqCutOffPolicy.always, VerifyType.POSITIVE),
        (SeqCutOffPolicy.full, VerifyType.NEGATIVE),
    ],
)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh(cache_line_size, io_dir, policy, verify_type):
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

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX * 4 + Size(value=5, unit=Unit.GibiByte))]
        )
        core_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX + Size(value=10, unit=Unit.GibiByte))]
        )
        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache and add core"):
        cache = casadm.start_cache(
            cache_dev=cache_part,
            force=True,
            cache_line_size=cache_line_size,
        )
        core = cache.add_core(core_dev=core_part)

        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size.generate_random_size(
            min_size=1,
            max_size=SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte),
            unit=Unit.KibiByte,
        )
        io_size = (threshold + fio_additional_size).align_down(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to {policy}"):
        cache.set_seq_cutoff_policy(policy)

    with TestRun.step(f"Setting cache sequential cut off policy threshold to {threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step("Prepare sequential IO against core"):
        sync()
        writes_before = core.get_statistics().block_stats.cache.writes
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(io_size)
            .read_write(io_dir)
            .target(f"{core.path}")
            .direct()
        )

    with TestRun.step("Run fio"):
        fio.run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(
            core=core,
            writes_before=writes_before,
            threshold=threshold,
            io_size=io_size,
            ver_type=verify_type,
        )


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("io_dir", [ReadWrite.write, ReadWrite.read])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_thresh_fill(cache_line_size, io_dir):
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

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]
        cache_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX + Size(value=5, unit=Unit.GibiByte))]
        )
        core_device.create_partitions(
            [(SEQ_CUTOFF_THRESHOLD_MAX + Size(value=10, unit=Unit.GibiByte))]
        )
        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache and add core"):
        cache = casadm.start_cache(
            cache_dev=cache_part,
            force=True,
            cache_line_size=cache_line_size,
        )
        core = cache.add_core(core_dev=core_part)

        fio_additional_size = Size(10, Unit.Blocks4096)
        threshold = Size.generate_random_size(
            min_size=1,
            max_size=SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte),
            unit=Unit.KibiByte,
        )
        io_size = (threshold + fio_additional_size).align_down(0x1000)

    with TestRun.step(f"Setting cache sequential cut off policy mode to {SeqCutOffPolicy.never}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Prepare sequential IO against core"):
        sync()
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(cache.size)
            .read_write(io_dir)
            .target(f"{core.path}")
            .direct()
        )

    with TestRun.step("Run fio"):
        fio.run()

    with TestRun.step("Check if cache is filled enough (expecting occupancy not less than 95%)"):
        occupancy_percentage = cache.get_statistics(percentage_val=True).usage_stats.occupancy
        if occupancy_percentage < 95:
            TestRun.fail(
                f"Cache occupancy is too small: {occupancy_percentage}, expected at least 95%"
            )

    with TestRun.step(f"Setting cache sequential cut off policy mode to {SeqCutOffPolicy.full}"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.full)

    with TestRun.step(f"Setting cache sequential cut off policy threshold to {threshold}"):
        cache.set_seq_cutoff_threshold(threshold)

    with TestRun.step(f"Running sequential IO ({io_dir})"):
        sync()
        writes_before = core.get_statistics().block_stats.cache.writes
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(io_size)
            .read_write(io_dir)
            .target(f"{core.path}")
            .direct()
        )

    with TestRun.step("Run fio"):
        fio.run()

    with TestRun.step("Verify writes to cache count"):
        verify_writes_count(core, writes_before, threshold, io_size, VerifyType.POSITIVE)


def verify_writes_count(
    core,
    writes_before,
    threshold,
    io_size,
    ver_type=VerifyType.NEGATIVE,
    io_margin=Size(8, Unit.KibiByte),
):
    writes_after = core.get_statistics().block_stats.cache.writes
    writes_difference = writes_after - writes_before
    match ver_type:
        case VerifyType.NEGATIVE:
            if writes_difference < io_size:
                TestRun.fail(
                    f"Wrong writes count: {writes_difference} , expected at least {io_size}"
                )
        case VerifyType.POSITIVE:
            if writes_difference >= threshold + io_margin:
                TestRun.fail(
                    f"Wrong writes count: {writes_difference} , expected at most "
                    f"{threshold + io_margin}"
                )
        case VerifyType.EQUAL:
            if writes_difference != io_size:
                TestRun.fail(f"Wrong writes count: {writes_difference} , expected {io_size}")
