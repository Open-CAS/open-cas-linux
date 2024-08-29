#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import random
import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
)
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit
from test_utils.os_utils import Udev
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_change_cleaning_policy_during_io_raw():
    """
    title: Test for changing the cleaning policy during background IO on raw device.
    description: |
        Stress test to change the cleaning policy during background IO operations on raw exported
        object in Write-Back cache mode.
    pass_criteria:
      - No system crash
      - Successful change of cleaning policy
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(500, Unit.MebiByte)])
        core_dev.create_partitions([Size(1, Unit.GibiByte)])

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in Write-Back mode"):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WB, force=True)

    with TestRun.step(f"Add core to the cache"):
        core = cache.add_core(core_dev)

    with TestRun.step("Run I/O in background"):
        fio = (
            Fio()
            .create_command()
            .target(core.path)
            .size(core.size)
            .read_write(ReadWrite.randrw)
            .io_engine(IoEngine.sync)
            .block_size(Size(1, Unit.Blocks4096))
        )

        fio_pid = fio.run_in_background()

    with TestRun.step(f"Start changing the cleaning policy during I/O operations"):
        current_policy = cache.get_cleaning_policy()
        while TestRun.executor.check_if_process_exists(fio_pid):
            random_policy = [policy for policy in list(CleaningPolicy) if policy != current_policy]
            policy_to_change = random.choice(random_policy)
            cache.set_cleaning_policy(policy_to_change)
            cache_policy = cache.get_cleaning_policy()
            if cache_policy != policy_to_change:
                TestRun.fail("Wrong cleaning policy after changing it during I/O")
            current_policy = cache_policy


@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_change_cleaning_policy_during_io_fs(filesystem):
    """
    title: Test for changing the cleaning policy during IO on exported object.
    description: |
        Stress test for changing the cleaning policy during IO operations on CAS device with a
        filesystem in Write-Back cache mode.
    pass_criteria:
      - No system crash
      - Successful change of cleaning policy
    """
    mount_point = "/mnt"

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(500, Unit.MebiByte)])
        core_dev.create_partitions([Size(1, Unit.GibiByte)])

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in Write-Back mode"):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WB, force=True)

    with TestRun.step(f"Create filesystem on core device"):
        core_dev.create_filesystem(filesystem)

    with TestRun.step(f"Add core to the cache"):
        core = cache.add_core(core_dev)

    with TestRun.step("Mount exported object"):
        core.mount(mount_point=mount_point)

    with TestRun.step("Run I/O in background on exported object"):
        fio = (
            Fio()
            .create_command()
            .size(core.size)
            .target(posixpath.join(mount_point, "test_file"))
            .read_write(ReadWrite.randrw)
            .io_engine(IoEngine.sync)
            .block_size(Size(1, Unit.Blocks4096))
        )

        fio_pid = fio.run_in_background()

    with TestRun.step(f"Start changing the cleaning policy during I/O operations"):
        current_policy = cache.get_cleaning_policy()
        while TestRun.executor.check_if_process_exists(fio_pid):
            random_policy = [policy for policy in list(CleaningPolicy) if policy != current_policy]
            policy_to_change = random.choice(random_policy)
            cache.set_cleaning_policy(policy_to_change)
            cache_policy = cache.get_cleaning_policy()
            if cache_policy != policy_to_change:
                TestRun.fail("Wrong cleaning policy after changing it during I/O")
            current_policy = cache_policy
