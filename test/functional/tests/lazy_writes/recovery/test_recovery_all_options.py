#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait, CacheLineSize, CleaningPolicy, \
    FlushParametersAcp
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.fs_tools import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.filesystem.file import File
from test_tools.os_tools import DropCachesMode, drop_caches, sync
from type_def.size import Size, Unit
from type_def.time import Time
from tests.lazy_writes.recovery.recovery_tests_methods import power_cycle_dut

test_file_size = Size(300, Unit.MebiByte)
mount_point = "/mnt"
filename = "fio_test_file"
pattern = "0xabcd"
other_pattern = "0x0000"


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_plugin("power_control")
def test_recovery_all_options(cache_mode, cache_line_size, cleaning_policy, filesystem):
    """
        title: Test for recovery after reset with various cache options.
        description: Verify that unflushed data can be safely recovered after reset.
        pass_criteria:
          - CAS recovers successfully after reboot
          - No data corruption
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(200, Unit.MebiByte)])
        core_disk.create_partitions([Size(2000, Unit.MebiByte)] * 2)
        cache_device = cache_disk.partitions[0]
        core_device = core_disk.partitions[0]

        test_file = File(os.path.join(mount_point, filename))
        file_operation(test_file.full_path, pattern, ReadWrite.write)
        file_md5 = test_file.md5sum()

    with TestRun.step(f"Make {filesystem} on core device."):
        core_device.create_filesystem(filesystem)

    with TestRun.step("Mount core device."):
        core_device.mount(mount_point)
        file_operation(test_file.full_path, other_pattern, ReadWrite.write)
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Unmount core device."):
        core_device.unmount()

    with TestRun.step(f"Start cache in {cache_mode.name} with given configuration."):
        cache = casadm.start_cache(cache_device, cache_mode, cache_line_size, force=True)
        cache.set_cleaning_policy(cleaning_policy)
        if cleaning_policy == CleaningPolicy.acp:
            cache.set_params_acp(FlushParametersAcp(wake_up_time=Time(seconds=1)))

    with TestRun.step("Add core."):
        core = cache.add_core(core_device)

    with TestRun.step("Mount CAS device."):
        core.mount(mount_point)
        file_operation(test_file.full_path, pattern, ReadWrite.write)

    with TestRun.step("Change cache mode to Write-Through without flush option."):
        cache.set_cache_mode(CacheMode.WT, flush=False)

    with TestRun.step("Reset platform."):
        sync()
        core.unmount()
        drop_caches(DropCachesMode.ALL)
        TestRun.LOGGER.info(f"Number of dirty blocks in cache: {cache.get_dirty_blocks()}")
        power_cycle_dut()

    with TestRun.step("Try to start cache without load and force option."):
        try:
            casadm.start_cache(cache_device, cache_mode, cache_line_size)
            TestRun.fail("Cache started without load or force option.")
        except Exception:
            TestRun.LOGGER.info("Cache did not start without load and force option.")

    with TestRun.step("Load cache and stop it with flush."):
        cache = casadm.load_cache(cache_device)
        cache.stop()

    with TestRun.step("Check md5sum of tested file on core device."):
        core_device.mount(mount_point)
        cas_md5 = test_file.md5sum()
        core_device.unmount()
        if cas_md5 == file_md5:
            TestRun.LOGGER.info("Source and target file checksums are identical.")
        else:
            TestRun.fail("Source and target file checksums are different.")

        core_disk.remove_partitions()
        cache_disk.remove_partitions()


def file_operation(target_path, data_pattern, io_pattern):
    fio = (Fio().create_command()
           .target(target_path)
           .io_engine(IoEngine.libaio)
           .size(test_file_size)
           .read_write(io_pattern)
           .block_size(Size(1, Unit.Blocks4096))
           .verification_with_pattern(data_pattern)
           .direct()
           .set_param("do_verify", 0))
    fio.run()
