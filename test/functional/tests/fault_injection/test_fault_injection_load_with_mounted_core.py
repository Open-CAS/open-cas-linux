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
from test_utils.prepare import prepare, prepare_with_file_creation


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
          - CAS device loads successfully.
    """
    with TestRun.step("Prepare cache and core. Start Open CAS."):
        cache_dev, core_dev = prepare("cache", "core")
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)

    with TestRun.step("Add core device with xfs filesystem and mount it."):
        core = cache.add_core(core_dev)
        core.create_filesystem(Filesystem.xfs)
        core.mount(mount_point)

    with TestRun.step(f"Create test file in {mount_point} directory and count its md5 sum."):
        file = File.create_file(test_file_path)
        file.write("Test content")
        md5_before_load = file.md5sum()
        size_before_load = file.size
        permissions_before_load = file.permissions
        file.refresh_item()

    with TestRun.step("Copy file to cache device and release core."):
        dd = Dd().input(file).output(cache).count(1)
        dd.run()
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
        check_files(core, size_before_load, permissions_before_load, md5_before_load)

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


def check_files(core, size_before, permissions_before, md5_before):
    TestRun.LOGGER.info("Checking file md5.")
    core.mount(mount_point)
    file_after = fs_utils.parse_ls_output(fs_utils.ls(test_file_path))[0]
    md5_after = file_after.md5sum()
    if md5_before != md5_after:
        TestRun.LOGGER.error(f"Md5 before ({md5_before}) and after ({md5_after}) are different.")

    if permissions_before.user == file_after.permissions.user:
        TestRun.LOGGER.error(f"User permissions before ({permissions_before.user}) "
                             f"and after ({file_after.permissions.user}) are different.")
    if permissions_before.group != file_after.permissions.group:
        TestRun.LOGGER.error(f"Group permissions before ({permissions_before.group}) "
                             f"and after ({file_after.permissions.group}) are different.")
    if permissions_before.other != file_after.permissions.other:
        TestRun.LOGGER.error(f"Other permissions before ({permissions_before.other}) "
                             f"and after ({file_after.permissions.other}) are different.")
    if size_before != file_after.size:
        TestRun.LOGGER.error(f"Size before ({size_before}) and after ({file_after.size}) "
                             f"are different.")
    core.unmount()
