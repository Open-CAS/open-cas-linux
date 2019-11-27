#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_cache_with_mounted_core(cache_mode):
    """
        title: Fault injection test for starting cache with mounted core.
        description: |
          False positive test of the ability of the CAS to load cache
          when core device is mounted.
        pass_criteria:
          - No system crash while load cache.
          - Loading core device fails.
    """
    with TestRun.step("Prepare cache and core. Start Open CAS."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(512, Unit.MebiByte)])
        core_dev = core_dev.partitions[0]
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

    with TestRun.step("Add core device with xfs filesystem and mount it."):
        core = cache.add_core(core_dev)
        core.create_filesystem(Filesystem.xfs)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in /big directory and count its md5 sum."):
        file = fs_utils.create_test_file('/big/test_file')

    with TestRun.step("Copy file to cache device"):
        copied_file = File.copy(file.full_path, test_file_path, force=True)

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop cache."):
        cache.stop()
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Mount core device."):
        core_dev.mount(mount_point)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache.cache_device)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 1:
            TestRun.fail(f"Expected caches count: 1 Actual caches count: {caches_count}.")
        cores_count = len(casadm_parser.get_cores(cache.cache_id))
        if cores_count != 0:
            TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")

    with TestRun.step("Check md5 of test file."):
        file1 = file.get_properties()
        file2 = copied_file.get_properties()
        if file1 != file2:
            TestRun.LOGGER.error("File properties before and after are different.")
        core_dev.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()
