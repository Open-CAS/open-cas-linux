#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from time import sleep

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    SeqCutOffPolicy,
)
from storage_devices.disk import DiskType, DiskTypeSet
from core.test_run import TestRun
from test_tools.os_tools import sync
from test_tools.scsi_debug import ScsiDebug
from test_tools.fs_tools import create_random_test_file, Filesystem
from type_def.size import Size, Unit

mount_point = "/mnt/cas"


@pytest.mark.os_dependent
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_request_propagation_cache():
    """
    title: Test for FLUSH requests propagation to cache device
    description: |
      Test if OpenCAS propagates FLUSH requests to underlaying cache device
    pass_criteria:
      - FLUSH requests should be propagated to cache device.
    """
    with TestRun.step("Load scsi_debug module."):
        scsi_debug = ScsiDebug({"dev_size_mb": "8192", "opts": "1"})

    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        scsi_debug.reset_stats()

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = scsi_debug.get_devices()[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache on SCSI device and add core with xfs filesystem"):
        cache = casadm.start_cache(cache_dev, CacheMode.WT)
        core_dev.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_dev)

    with TestRun.step("Turn off cleaning policy and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Mount exported object."):
        if core.is_mounted():
            core.unmount()
        core.mount(mount_point)
        sync()

    with TestRun.step("Create temporary file on the exported object."):
        scsi_debug.reset_stats()
        create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        sync()
        sleep(3)

    with TestRun.step("Check for flush request."):
        if scsi_debug.get_flush_count() == 0:
            TestRun.LOGGER.error("Flush request not occured")

    with TestRun.step("Unmount exported object."):
        core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unload scsi_debug module."):
        scsi_debug.unload()


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_request_propagation_core():
    """
    title: Test for FLUSH requests propagation to core device
    description: |
      Test if OpenCAS propagates FLUSH requests to underlaying core device
    pass_criteria:
      - FLUSH requests should be propagated to core device.
    """
    with TestRun.step("Load scsi_debug module."):
        scsi_debug = ScsiDebug({"dev_size_mb": "8192", "opts": "1"})

    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        scsi_debug.reset_stats()

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks["cache"]
        core_dev = scsi_debug.get_devices()[0]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]

    with TestRun.step("Start cache and add SCSI device with xfs filesystem as core."):
        cache = casadm.start_cache(cache_dev, CacheMode.WT)
        core_dev.create_filesystem(Filesystem.xfs)
        core = cache.add_core(core_dev)

    with TestRun.step("Turn off cleaning policy and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Mount exported object."):
        if core.is_mounted():
            core.unmount()
        core.mount(mount_point)
        sync()

    with TestRun.step("Create temporary file on the exported object."):
        scsi_debug.reset_stats()
        create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        sync()
        sleep(3)

    with TestRun.step("Check for flush request."):
        if scsi_debug.get_flush_count() == 0:
            TestRun.LOGGER.error("Flush request not occured")

    with TestRun.step("Unmount exported object."):
        core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unload scsi_debug module."):
        scsi_debug.unload()
