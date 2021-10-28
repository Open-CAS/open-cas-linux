#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import os
import random
from time import sleep

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, SeqCutOffPolicy, CacheModeTrait
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit

random_thresholds = random.sample(range(1028, 1024 ** 2, 4), 3)
random_stream_numbers = random.sample(range(2, 128), 3)


@pytest.mark.parametrizex("streams_number", [1, 128] + random_stream_numbers)
@pytest.mark.parametrizex("threshold",
                          [Size(1, Unit.MebiByte), Size(1, Unit.GibiByte)]
                          + [Size(x, Unit.KibiByte) for x in random_thresholds])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_multistream_seq_cutoff_functional(threshold, streams_number):
    """
    title: Functional test for multistream sequential cutoff
    description: |
        Testing if amount of data written to cache and core is correct after running sequential
        writes from multiple streams with different sequential cut-off thresholds.
    pass_criteria:
        - Amount of data written to cache is equal to amount set with sequential cutoff threshold
        - Amount of data written in pass-through is equal to io size run after reaching the
        sequential cutoff threshold
    """
    with TestRun.step("Start cache and add core device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']

        cache = casadm.start_cache(cache_disk, CacheMode.WB, force=True)
        Udev.disable()
        core = cache.add_core(core_disk)

    with TestRun.step(f"Set seq-cutoff policy to always, threshold to {threshold} "
                      f"and reset statistics counters."):
        core.set_seq_cutoff_policy(SeqCutOffPolicy.always)
        core.set_seq_cutoff_threshold(threshold)
        core.set_seq_cutoff_promotion_count(1)
        core.reset_counters()

    with TestRun.step(f"Run {streams_number} I/O streams with amount of sequential writes equal to "
                      f"seq-cutoff threshold value minus one 4k block."):
        kib_between_streams = 100
        range_step = int(threshold.get_value(Unit.KibiByte)) + kib_between_streams
        max_range_offset = streams_number * range_step

        offsets = [o for o in range(0, max_range_offset, range_step)]
        core_statistics_before = core.get_statistics()

        for i in TestRun.iteration(range(0, len(offsets))):
            TestRun.LOGGER.info(f"Statistics before I/O:\n{core_statistics_before}")

            offset = Size(offsets[i], Unit.KibiByte)
            run_dd(core.path, count=int(threshold.get_value(Unit.Blocks4096) - 1),
                   seek=int(offset.get_value(Unit.Blocks4096)))

            core_statistics_after = core.get_statistics()
            check_statistics(core_statistics_before,
                             core_statistics_after,
                             expected_pt=0,
                             expected_writes_to_cache=threshold - Size(1, Unit.Blocks4096))
            core_statistics_before = core_statistics_after

    with TestRun.step("Write random number of 4k block requests to each stream and check if all "
                      "writes were sent in pass-through mode."):
        core_statistics_before = core.get_statistics()
        random.shuffle(offsets)

        for i in TestRun.iteration(range(0, len(offsets))):
            TestRun.LOGGER.info(f"Statistics before second I/O:\n{core_statistics_before}")
            additional_4k_blocks_writes = random.randint(1, kib_between_streams / 4)
            offset = Size(offsets[i], Unit.KibiByte)
            run_dd(
                core.path, count=additional_4k_blocks_writes,
                seek=int(offset.get_value(Unit.Blocks4096)
                         + threshold.get_value(Unit.Blocks4096) - 1))

            core_statistics_after = core.get_statistics()
            check_statistics(core_statistics_before,
                             core_statistics_after,
                             expected_pt=additional_4k_blocks_writes,
                             expected_writes_to_cache=Size.zero())
            core_statistics_before = core_statistics_after


def check_statistics(stats_before, stats_after, expected_pt, expected_writes_to_cache):
    TestRun.LOGGER.info(f"Statistics after I/O:\n{stats_after}")
    writes_to_cache_before = stats_before.block_stats.cache.writes
    writes_to_cache_after = stats_after.block_stats.cache.writes
    pt_writes_before = stats_before.request_stats.pass_through_writes
    pt_writes_after = stats_after.request_stats.pass_through_writes

    actual_pt = pt_writes_after - pt_writes_before
    actual_writes_to_cache = writes_to_cache_after - writes_to_cache_before
    if actual_pt != expected_pt:
        TestRun.LOGGER.error(f"Expected pass-through writes: {expected_pt}\n"
                             f"Actual pass-through writes: {actual_pt}")
    if actual_writes_to_cache != expected_writes_to_cache:
        TestRun.LOGGER.error(
            f"Expected writes to cache: {expected_writes_to_cache}\n"
            f"Actual writes to cache: {actual_writes_to_cache}")


def run_dd(target_path, count, seek):
    dd = Dd() \
        .input("/dev/zero") \
        .output(target_path) \
        .block_size(Size(1, Unit.Blocks4096)) \
        .count(count) \
        .oflag("direct") \
        .seek(seek)
    dd.run()
    TestRun.LOGGER.info(f"dd command:\n{dd}")


@pytest.mark.parametrizex("streams_seq_rand", [(64, 64), (64, 192)])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_multistream_seq_cutoff_stress_raw(streams_seq_rand):
    """
    title: Stress test for multistream sequential cutoff on raw device
    description: |
        Testing the stability of a system when there are multiple sequential and random I/O streams
        running against the raw exported object with the sequential cutoff policy set to always and
        the sequential cutoff threshold set to a value which is able to be reached by
        sequential I/O streams.
    pass_criteria:
        - No system crash
    """
    with TestRun.step("Start cache and add core device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(1.5, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        cache = casadm.start_cache(cache_dev, CacheMode.WB, force=True)
        Udev.disable()
        core = cache.add_core(core_disk)

    with TestRun.step(f"Set seq-cutoff policy to always and threshold to 512KiB."):
        core.set_seq_cutoff_policy(SeqCutOffPolicy.always)
        core.set_seq_cutoff_threshold(Size(512, Unit.KibiByte))

    with TestRun.step("Reset core statistics counters."):
        core.reset_counters()

    with TestRun.step("Run I/O"):
        stream_size = min(core_disk.size / 256, Size(256, Unit.MebiByte))
        sequential_streams = streams_seq_rand[0]
        random_streams = streams_seq_rand[1]
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .block_size(Size(1, Unit.Blocks4096))
               .direct()
               .offset_increment(stream_size))

        for i in range(0, sequential_streams + random_streams):
            fio_job = fio.add_job(job_name=f"stream_{i}")
            fio_job.size(stream_size)
            fio_job.target(core.path)
            if i < sequential_streams:
                fio_job.read_write(ReadWrite.write)
            else:
                fio_job.read_write(ReadWrite.randwrite)

        pid = fio.run_in_background()
        while TestRun.executor.check_if_process_exists(pid):
            sleep(5)
            TestRun.LOGGER.info(f"{core.get_statistics()}")


@pytest.mark.parametrizex("streams_seq_rand", [(64, 64), (64, 192)])
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_multistream_seq_cutoff_stress_fs(streams_seq_rand, filesystem, cache_mode):
    """
    title: Stress test for multistream sequential cutoff on the device with a filesystem
    description: |
        Testing the stability of a system when there are multiple sequential and random I/O streams
        running against the exported object with a filesystem when the sequential cutoff policy is
        set to always and the sequential cutoff threshold is set to a value which is able
        to be reached by sequential I/O streams.
    pass_criteria:
        - No system crash
    """
    mount_point = "/mnt"
    with TestRun.step("Prepare devices. Create filesystem on core device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        core_disk.create_filesystem(filesystem)

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_disk, cache_mode, force=True)
        Udev.disable()
        core = cache.add_core(core_disk)

    with TestRun.step("Mount core."):
        core.mount(mount_point)

    with TestRun.step(f"Set seq-cutoff policy to always and threshold to 20MiB."):
        core.set_seq_cutoff_policy(SeqCutOffPolicy.always)
        core.set_seq_cutoff_threshold(Size(20, Unit.MebiByte))

    with TestRun.step("Reset core statistics counters."):
        core.reset_counters()

    with TestRun.step("Run I/O"):
        sequential_streams = streams_seq_rand[0]
        random_streams = streams_seq_rand[1]
        stream_size = core_disk.size / 256
        fio = (Fio().create_command()
               .io_engine(IoEngine.libaio)
               .block_size(Size(1, Unit.Blocks4096))
               .direct()
               .offset_increment(stream_size))

        for i in range(0, sequential_streams + random_streams):
            fio_job = fio.add_job(job_name=f"stream_{i}")
            fio_job.size(stream_size)
            fio_job.target(os.path.join(mount_point, f"file_{i}"))
            if i < sequential_streams:
                fio_job.read_write(ReadWrite.write)
            else:
                fio_job.read_write(ReadWrite.randwrite)

        pid = fio.run_in_background()
        while TestRun.executor.check_if_process_exists(pid):
            sleep(5)
            TestRun.LOGGER.info(f"{core.get_statistics()}")
