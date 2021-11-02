#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest
from api.cas import casadm, casadm_parser
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_occupied_id():
    """
        title: Negative test for loading cache with occupied ID.
        description: |
          Verify that loading cache with occupied ID is not permitted.
        pass_criteria:
          - Loading cache with occupied ID should fail.
    """

    with TestRun.step("Create partitions for test."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']
        cache_device.create_partitions([Size(500, Unit.MebiByte), Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        cache_device_1 = cache_device.partitions[0]
        cache_device_2 = cache_device.partitions[1]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache with default id and one core."):
        cache1 = casadm.start_cache(cache_device_1, force=True)
        cache1.add_core(core_device)

    with TestRun.step("Stop cache."):
        cache1.stop()

    with TestRun.step("Start cache with default id on different device."):
        casadm.start_cache(cache_device_2, force=True)

    with TestRun.step("Attempt to load metadata from first cache device."):
        try:
            casadm.load_cache(cache_device_1)
            TestRun.fail("Cache loaded successfully but it should not.")
        except Exception:
            pass

        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.LOGGER.error("Inappropriate number of caches after load!")
        if caches[0].cache_device.path != cache_device_2.path:
            TestRun.LOGGER.error("Wrong cache device system path!")
        if caches[0].cache_id != 1:
            TestRun.LOGGER.error("Wrong cache id.")

        cores = caches[0].get_core_devices()
        if len(cores) != 0:
            TestRun.LOGGER.error("Inappropriate number of cores after load!")
