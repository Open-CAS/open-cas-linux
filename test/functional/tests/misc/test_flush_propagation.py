#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re
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
from test_tools.disk_utils import Filesystem
from test_utils.scsi_debug import Logs, syslog_path
from test_tools.fs_utils import create_random_test_file
from test_utils import os_utils
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug_fua_signals", dev_size_mb="8192", opts="1")
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_signal_propagation_cache():
    """
    title: Test for FLUSH signals propagation to cache device
    description: |
      Test if OpenCAS propagates FLUSH signal to underlaying cache device
    pass_criteria:
      - FLUSH requests should be propagated to cache device.
    """
    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        Logs._read_syslog(Logs.last_read_line)

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.scsi_debug_devices[0]
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
        os_utils.sync()

    with TestRun.step("Create temporary file on the exported object."):
        Logs._read_syslog(Logs.last_read_line)
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()
        sleep(3)

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_flush()
        tmp_file.remove(True)


@pytest.mark.os_dependent
@pytest.mark.require_plugin("scsi_debug_fua_signals", dev_size_mb="8192", opts="1")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_flush_signal_propagation_core():
    """
    title: Test for FLUSH signals propagation to core device
    description: |
      Test if OpenCAS propagates FLUSH signal to underlaying core device
    pass_criteria:
      - FLUSH requests should be propagated to core device.
    """
    with TestRun.step("Set mark in syslog to not read entries existing before the test."):
        Logs._read_syslog(Logs.last_read_line)

    with TestRun.step("Prepare devices for cache and core."):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.scsi_debug_devices[0]
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
        os_utils.sync()

    with TestRun.step("Create temporary file on the exported object."):
        Logs._read_syslog(Logs.last_read_line)
        tmp_file = create_random_test_file(f"{mount_point}/tmp.file", Size(1, Unit.GibiByte))
        os_utils.sync()
        sleep(3)

    with TestRun.step(f"Check {syslog_path} for flush request and delete temporary file."):
        Logs.check_syslog_for_flush()
        tmp_file.remove(True)
