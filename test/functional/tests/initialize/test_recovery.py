#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.casadm_parser import get_caches
from api.cas.cli import stop_cmd
from api.cas.cli_messages import check_stderr_msg, stop_cache_errors
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem, mount
from test_tools.fs_utils import check_if_file_exists
from test_utils.filesystem.file import File
from test_utils.os_utils import sync
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"


@pytest.mark.CI
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_recover_cache_verify_core_device(filesystem):
    """
    title: Recovery after unplug/plug cache device
    description: |
        Test data integrity after unplug cache device.
    pass_criteria:
      - Cache devices successfully loaded with metadata after unplug/plug device
      - md5sums before and after all operations match each other
      - creation, mount, unmount of filesystems on the core device succeeds
      - correct error warning after cache stop
    """

    with TestRun.step("Partition cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(2, Unit.GibiByte)])
        core_device.create_partitions([Size(4, Unit.GibiByte)])

        cache_dev = cache_device.partitions[0]
        core_dev = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev=cache_dev, cache_mode=CacheMode.WB)
        core = cache.add_core(core_dev=core_dev)

    with TestRun.step("Create filesystem on core"):
        core.create_filesystem(filesystem)

    with TestRun.step("Mount exported object"):
        core.mount(mount_point)

    with TestRun.step("Run IO"):
        dd = (
            Dd()
            .input("/dev/urandom")
            .output(f"{mount_point}/test")
            .count(1)
            .block_size(Size(50, Unit.MegaByte))
        )
        dd.run()
        sync()

    with TestRun.step("Calculate test file md5sums before unplug"):
        core_mnt_md5s_before = File(f"{mount_point}/test").md5sum()

    with TestRun.step("Unmount exported object"):
        core.unmount()

    with TestRun.step("Unplug cache device"):
        cache_device.unplug()

    with TestRun.step("Stop cache without flushing and check error message"):
        output = TestRun.executor.run(stop_cmd(cache_id=str(cache.cache_id), no_data_flush=True))
        if len(get_caches()) > 0:
            TestRun.fail("CAS failed to stop cache")
        if not check_stderr_msg(output, stop_cache_errors):
            TestRun.fail(f"Wrong error message during cache stop")

    with TestRun.step("Plug cache device"):
        cache_device.plug_all()

    with TestRun.step("Load cache"):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Mount core device"):
        core.core_device.mount(mount_point)

    with TestRun.step("Calculate test file md5sums after recovery"):
        core_mnt_md5s_after = File(f"{mount_point}/test").md5sum()

    with TestRun.step("Compare test file md5 sums"):
        if core_mnt_md5s_before != core_mnt_md5s_after:
            TestRun.fail(
                f"MD5 sums do not match\n"
                f"Expected: {core_mnt_md5s_before}, Actual: {core_mnt_md5s_after}"
            )


@pytest.mark.CI
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_recover_cache_verify_exp_obj(filesystem):
    """
    title: Recovery after unplug/plug cache device
    description: |
        Test data integrity after unplug cache device.
    pass_criteria:
      - Cache device successfully loaded with metadata after unplug/plug cache device
      - md5sums before and after all operations match each other
      - creation, mount, unmount of filesystems succeeds on core exported object
    """

    with TestRun.step("Partition cache and core device"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(2, Unit.GibiByte)])
        core_device.create_partitions([Size(4, Unit.GibiByte)])

        cache_dev = cache_device.partitions[0]
        core_dev = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev=cache_dev, cache_mode=CacheMode.WB)
        core = cache.add_core(core_dev=core_dev)

    with TestRun.step("Create filesystem on core"):
        core.create_filesystem(filesystem)

    with TestRun.step("Mount exported object"):
        core.mount(mount_point)

    with TestRun.step("Run IO"):
        dd = (
            Dd()
            .input("/dev/urandom")
            .output(f"{mount_point}/test")
            .count(1)
            .block_size(Size(50, Unit.MegaByte))
        )
        dd.run()
        sync()

    with TestRun.step("Calculate test file md5sums before unplug"):
        core_mnt_md5s_before = File(f"{mount_point}/test").md5sum()

    with TestRun.step("Unmount exported object"):
        core.unmount()

    with TestRun.step("Unplug cache device"):
        cache_device.unplug()

    with TestRun.step("Stop cache without flushing and check error message"):
        output = TestRun.executor.run(stop_cmd(cache_id=str(cache.cache_id), no_data_flush=True))
        if len(get_caches()) > 0:
            TestRun.fail("CAS failed to stop cache")
        if not check_stderr_msg(output, stop_cache_errors):
            TestRun.fail(f"Wrong error message during cache stop")

    with TestRun.step("Plug cache device"):
        cache_device.plug_all()

    with TestRun.step("Load cache"):
        casadm.load_cache(cache_dev)

    with TestRun.step("Mount exported object"):
        core.mount(mount_point)
        if not check_if_file_exists(core.mount_point):
            TestRun.LOGGER.error(f"Mounting exported object {mount_point} failed")

    with TestRun.step("Calculate test file md5sums after recovery"):
        core_mnt_md5s_after = File(f"{core.mount_point}/test").md5sum()

    with TestRun.step("Compare test file md5 sums"):
        if core_mnt_md5s_before != core_mnt_md5s_after:
            TestRun.fail(
                f"MD5 sums do not match\n"
                f"Expected: {core_mnt_md5s_before}, Actual: {core_mnt_md5s_after}"
            )
