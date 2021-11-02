#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.core import CoreStatus
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_attach_core_pool():
    """
    title: Attaching from core pool on cache load.
    description: |
      Check that CAS has the ability on cache load to attach core devices that were added to
      core device pool if those devices were previously used by cache instance being loaded.
      Prevent attaching core device if they were not previously used.
    pass_criteria:
      - No system crash while reloading CAS modules.
      - Core device was added successfully to core pool.
      - Core device has been successfully attached to cache on cache load.
      - Second core device was not attached to the cache instance.
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(2, Unit.GibiByte), Size(2, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]
        second_core_dev = core_disk.partitions[1]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, force=True)

    with TestRun.step("Add core device."):
        cache.add_core(core_dev)

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Add previously used core device to core pool using --try-add flag."):
        first_core = casadm.try_add(core_dev, cache.cache_id)

    with TestRun.step("Add different core device to core pool using --try-add flag."):
        second_core = casadm.try_add(second_core_dev, cache.cache_id)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Check each core status."):
        if first_core.get_status() is not CoreStatus.active:
            TestRun.fail(f"First core status should be active but is {first_core.get_status()}.")
        if second_core.get_status() is not CoreStatus.detached:
            TestRun.fail(
                f"Second core status should be detached but is {second_core.get_status()}.")

    with TestRun.step("Stop cache and remove core from core pool."):
        casadm.remove_all_detached_cores()
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_core_pool_exclusive_open():
    """
    title: Exclusive open of core pool.
    description: |
      Check that CAS exclusively opens core devices from core device pool so that the core device
      cannot be used in any other way.
    pass_criteria:
      - No system crash while reloading CAS modules.
      - Core device was added successfully to core pool.
      - Core device is exclusively open in the core pool and cannot be used otherwise.
    """
    with TestRun.step("Prepare core device and create filesystem on it."):
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]
        core_dev.create_filesystem(Filesystem.ext4)

    with TestRun.step("Add core device to core device pool using --try-add flag."):
        core = casadm.try_add(core_dev, 1)

    with TestRun.step("Check if core status of added core in core pool is detached."):
        status = core.get_status()
        if status is not CoreStatus.detached:
            TestRun.fail(f"Core status should be detached but is {status}.")

    with TestRun.step("Check if it is impossible to add core device from core pool to "
                      "running cache."):
        TestRun.disks["cache"].create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = TestRun.disks["cache"].partitions[0]
        cache = casadm.start_cache(cache_dev, force=True)
        try:
            cache.add_core(core_dev)
            TestRun.fail("Core from core pool added to cache, this is unexpected behaviour.")
        except CmdException:
            TestRun.LOGGER.info("Adding core from core pool to cache is blocked as expected.")
        cache.stop()

    with TestRun.step("Check if it is impossible to start cache with casadm start command on the "
                      "core device from core pool."):
        try:
            cache = casadm.start_cache(core_dev)
            cache.stop()
            TestRun.fail("Cache started successfully on core device from core pool, "
                         "this is unexpected behaviour.")
        except CmdException:
            TestRun.LOGGER.info("Using core device from core pool as cache is blocked as expected.")

    with TestRun.step("Check if it is impossible to make filesystem on the core device "
                      "from core pool."):
        try:
            core_dev.create_filesystem(Filesystem.ext4, force=False)
            TestRun.fail("Successfully created filesystem on core from core pool, "
                         "this is unexpected behaviour.")
        except Exception:
            TestRun.LOGGER.info("Creating filesystem on core device from core pool is "
                                "blocked as expected.")

    with TestRun.step("Check if it is impossible to mount the core device from core pool."):
        try:
            core_dev.mount("/mnt")
            TestRun.fail("Successfully mounted core pool device, this is unexpected behaviour.")
        except Exception:
            TestRun.LOGGER.info("Mounting core device form core pool is blocked as expected.")

    with TestRun.step("Remove core from core pool."):
        casadm.remove_all_detached_cores()
