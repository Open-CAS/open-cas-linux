#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.casadm_parser import get_caches
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from type_def.size import Size, Unit
from api.cas.cache_config import CacheStatus


@pytest.mark.CI
@pytest.mark.skip(reason="Standby mode is not supported")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_standby_activate_the_same_cache_path():
    """
        title: Activate the same cache path
        description: |
            Test for loading and activating standby cache from existing metadata.
        pass_criteria:
          - Successfully prepare a partition and create cache instance partition, then stop it.
          - Standby cache loaded on the partition with valid CAS metadata.
          - Successfully detach standby cache.
          - Activate cache by path.
    """
    with TestRun.step("Prepare a partition."):
        cache = TestRun.disks["cache"]
        cache.create_partitions([Size(200, Unit.MebiByte)])
        cache_dev = cache.partitions[0]

    with TestRun.step("Start a regular cache instance on the partition and stop it."):
        cache = casadm.start_cache(cache_dev, force=True)
        cache.stop()

    with TestRun.step("Load standby cache on the partition with valid CAS metadata."):
        cache = casadm.standby_load(cache_dev)

    with TestRun.step("Detach standby cache"):
        cache.standby_detach()

    with TestRun.step("Activate cache providing path to the partition."):
        cache.standby_activate(device=cache_dev)
        caches = get_caches()
        cache_status = caches[0].get_status()
        if cache_status != CacheStatus.running:
            TestRun.LOGGER.error("Failed to activate cache with provided path.")
