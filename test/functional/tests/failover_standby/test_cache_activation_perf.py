#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from datetime import timedelta, datetime

import pytest

from core.test_run import TestRun
from test_tools.dd import Dd
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.device import Device
from api.cas import casadm, dmesg
from api.cas.cache_config import CleaningPolicy, CacheMode, CacheLineSize, SeqCutOffPolicy

activation_time_threshold = timedelta(seconds=10)
test_drive_size = Size(800, Unit.GibiByte)
prefill_threshold = 99.5
non_prefill_threshold = 0.0
fio_jobs = 4
cls = CacheLineSize.LINE_4KiB


@pytest.mark.CI
@pytest.mark.require_disk("cache_1", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("cache_2", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k]))
@pytest.mark.parametrize("prefill", [True, False])
def test_cache_activation_time(prefill):
    """
    title: Measure standby cache activation time
    description: Determine if the activation of a standby cache completes within
                 a predefined time limit, on empty and prefilled devices
    pass_criteria:
      - The activation completes within the time limit
    """
    with TestRun.step(f"Setting up two cache devices, {test_drive_size} each"):
        cache_devices = [TestRun.disks['cache_1'], TestRun.disks['cache_2']]
        core_device = TestRun.disks['core']

        # cache devices - check size and create partitions
        for cache_dev in cache_devices:
            check_disk_size(cache_dev)
            cache_dev.create_partitions([test_drive_size])

        # core partition creation
        check_disk_size(core_device)
        core_device.create_partitions([test_drive_size])

    with TestRun.step("Start cache and add core"):
        Udev.disable()
        cache = casadm.start_cache(cache_devices[0].partitions[0],
                                   force=True,
                                   cache_mode=CacheMode.WB,
                                   cache_line_size=cls)

        core = cache.add_core(core_device.partitions[0])
        current_cache_id = cache.cache_id

    with TestRun.step("Disable seq. cutoff, cleaning policy"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step(f"Pre-filling the cache with dirty data to target threshold"):
        if prefill is True:
            TestRun.LOGGER.info(f"Target prefill threshold: {prefill_threshold}%")

            fill_size = test_drive_size
            (
                Fio()
                .create_command()
                .io_engine(IoEngine.libaio)
                .block_size(Size(1, Unit.MiB))
                .read_write(ReadWrite.write)
                .target(core)
                .size(fill_size/fio_jobs)
                .direct()
                .num_jobs(fio_jobs)
                .offset_increment(fill_size/fio_jobs)
                .run()
            )
        else:
            TestRun.LOGGER.info(f"Target prefill threshold: 0% - prefill skipped")

    with TestRun.step("Check usage statistics after pre-fill"):
        stats = cache.get_statistics(percentage_val=True)

        if prefill is True:
            if stats.usage_stats.dirty < prefill_threshold or \
                    stats.usage_stats.occupancy < prefill_threshold:
                TestRun.LOGGER.error(f"Cache is not pre-filled correctly, "
                                     f"dirty={stats.usage_stats.dirty}%, "
                                     f"occupancy={stats.usage_stats.occupancy}%")
        else:
            if stats.usage_stats.dirty > non_prefill_threshold or \
                    stats.usage_stats.occupancy > non_prefill_threshold:
                TestRun.LOGGER.error(f"Cache contains data, "
                                     f"dirty={stats.usage_stats.dirty}%, "
                                     f"occupancy={stats.usage_stats.occupancy}%")

    with TestRun.step("Get metadata size"):
        dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout
        md_size = dmesg.get_metadata_size_on_device(dmesg_out)

    with TestRun.step("Stop the cache without flushing."):
        cache.stop(no_data_flush=True)

    with TestRun.step("initialize standby instance with cls = 4k"):
        standby_cache = casadm.standby_init(cache_dev=cache_devices[1].partitions[0],
                                            cache_line_size=cls,
                                            cache_id=current_cache_id)

    with TestRun.step("verify cache exported object has appeared"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep cas-cache-1")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")

    with TestRun.step("Copy valid metadata to the standby cache exp. obj."):
        dd_count = int(md_size / Size(1, Unit.MebiByte)) + 1
        (
            Dd()
            .input(cache_devices[0].partitions[0].path)
            .output("/dev/cas-cache-1")
            .block_size(Size(1, Unit.MebiByte))
            .count(dd_count)
            .run()
        )

    with TestRun.step("Detach the standby cache"):
        standby_cache.standby_detach()

    with TestRun.step("Verify exp. obj. disappeared"):
        TestRun.executor.run_expect_fail(f"ls -la /dev/ | grep cas-cache-1")

    with TestRun.step("Activate passive cache and measure the activation time"):
        start_time = datetime.now()
        standby_cache.standby_activate(cache_devices[1].partitions[0])
        end_time = datetime.now()

        elapsed_time = end_time - start_time

        TestRun.LOGGER.info(f"Cache activation time: {elapsed_time}")

        if elapsed_time > activation_time_threshold:
            TestRun.fail(f"Activation time {elapsed_time} exceeds "
                         f"time threshold of {activation_time_threshold}")

        if elapsed_time + timedelta(seconds=0.5) > activation_time_threshold:
            TestRun.LOGGER.warning("Cache activation time is close to the threshold!")


def check_disk_size(device: Device):
    if device.size < test_drive_size:
        pytest.skip(f"Not enough space on device {device.path}.")
