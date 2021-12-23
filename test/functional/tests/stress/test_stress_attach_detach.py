#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import random

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_attach_detach():
    """
        title: Stress test for attaching and detaching multiple core devices.
        description: |
          Validate the ability of CAS to attach and detach core devices using script commands.
        pass_criteria:
          - No system crash.
          - Core devices are successfully attached and detached.
    """
    iterations_number = 50

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(100, Unit.MebiByte)])
        cache_part = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(5, Unit.GibiByte)] * 8)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part)
        cores = []
        for dev in core_devices:
            cores.append(cache.add_core(dev))

    with TestRun.step("Attach and detach core devices in a loop."):
        for _ in TestRun.iteration(range(0, iterations_number)):
            TestRun.LOGGER.info("Detaching all core devices.")
            for core in cores:
                casadm.detach_core(cache.cache_id, core.core_id)

            random.shuffle(cores)

            TestRun.LOGGER.info("Attaching all core devices.")
            for core in cores:
                casadm.try_add(core.core_device, cache.cache_id, core.core_id)
