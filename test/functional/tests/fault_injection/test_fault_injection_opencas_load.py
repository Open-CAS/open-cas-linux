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
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.parametrize("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_n_load_cache(cache_mode, filesystem):
    """
        title: Fault injection test to check that OpenCAS 'stop -n' option works correctly.
        description: |
          False positive test of the ability of the CAS to load unflushed cache
          when core device is mounted and unmounted.
        pass_criteria:
          - No system crash while load cache.
          - Loading cache without loading metadata fails.
          - Loading cache with loading metadata finishes with success.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start proper tests"):
        stop_n_load_cache_fs(cache_mode, filesystem, cache_dev, core_dev)
        stop_n_load_cache_notfs(cache_mode, cache_dev, core_dev)


def stop_n_load_cache_fs(cache_mode, filesystem, cache_dev, core_dev):
    with TestRun.step("Start Open CAS."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

    with TestRun.step("Add core device with xfs filesystem and mount it."):
        core = cache.add_core(core_dev)
        core.create_filesystem(filesystem)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in /big directory and count its md5 sum."):
        file = fs_utils.create_test_file('/big/test_file',
                                         'There is nothing interesting inside this file.')

    with TestRun.step("Copy file to cache device"):
        copied_file = File.copy(file.full_path, test_file_path, force=True)

    with TestRun.step("Unmount core device."):
        core.unmount()

    with TestRun.step("Stop cache with option '-n'."):
        cache.stop(no_data_flush=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Mount core device."):
        core_dev.mount(mount_point)

    with TestRun.step("Try start cache without loading metadata."):
        try:
            cache = casadm.start_cache(cache_dev, cache_mode, force=False)
        except Exception:
            TestRun.LOGGER.info("Can't start cache as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 0:
                TestRun.fail(f"Expected caches count: 0 Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 0:
                TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")

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
            TestRun.LOGGER.error("File properties before copying and after are different.")
        core_dev.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


def stop_n_load_cache_notfs(cache_mode, cache_dev, core_dev):
    with TestRun.step("Start Open CAS."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

    with TestRun.step("Add core device without filesystem."):
        core = cache.add_core(core_dev)

    with TestRun.step("Copy data to cache device"):
        dd = (Dd()
              .input("/dev/urandom")
              .output(f"{cache_dev.system_path}")
              .block_size(Size(512, Unit.Byte)))
        dd.run()

    with TestRun.step("Stop cache with option '-n'."):
        cache.stop(no_data_flush=True)
        caches_count = len(casadm_parser.get_caches())
        if caches_count != 0:
            TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Mount core device."):
        core_dev.mount(mount_point)

    with TestRun.step("Try start cache without loading metadata."):
        try:
            casadm.start_cache(cache_dev, cache_mode, force=False)
        except Exception:
            TestRun.LOGGER.info("Can't start cache as expected.")
        finally:
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 0:
                TestRun.fail(f"Expected caches count: 0 Actual caches count: {caches_count}.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()
