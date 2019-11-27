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
        if file.get_properties() != copied_file.get_properties():
            TestRun.LOGGER.error("File properties before and after are different.")
        core_dev.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_cache_with_mounted_partition(cache_mode):
    """
        title: Fault injection test for stopping the OpenCAS with mounted partition.
        description: |
          False positive test of the ability stop while partition
          is still mounted on Open CAS device.
        pass_criteria:
          - No system crash while load cache.
          - Unable to stop CAS device.
          -Unable to remove module when partition is mounted.
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

    with TestRun.step("Try to remove core from cache."):
        try:
            cache.remove_core(1, 1)
        except Exception:
            TestRun.LOGGER.info("Can't remove core as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Try to stop OpenCAS."):
        try:
            cache.stop()
        except Exception:
            TestRun.LOGGER.info("Can't stop OpenCAS as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_occupied_core(cache_mode):
    """
        title: Fault injection test to adding occupied core to the OpenCAS.
        description: |
          False positive test of the ability to add core to OpenCAS
          while its occupied by the another OpenCAS instance.
        pass_criteria:
          - The same core device cannot be used twice in CAS.
    """
    with TestRun.step("Prepare two caches and one core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte), Size(2, Unit.GibiByte)])
        cache_dev1 = cache_dev.partitions[0]
        cache_dev2 = cache_dev.partitions[1]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start first OpenCAS instance"):
        cache1 = casadm.start_cache(cache_dev1, cache_mode, force=True)

    with TestRun.step("Add core device to first OpenCAS instance."):
        cache1.add_core(core_dev)

    with TestRun.step("Start second OpenCAS instance"):
        cache2 = casadm.start_cache(cache_dev2, cache_mode, force=True)

    with TestRun.step("try add the same core device to second OpenCAS instance."):
        try:
            cache2.add_core(core_dev)
        except Exception:
            TestRun.LOGGER.info("Can't add this core as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 2:
                TestRun.fail(f"Expected caches count: 2; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache1.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")
            cores_count = len(casadm_parser.get_cores(cache2.cache_id))
            if cores_count != 0:
                TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()
