#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import random

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_attach_detach_core():
    """
    title: Stress test for attaching and detaching multiple core devices.
    description: |
        Validate the ability of CAS to attach and detach core devices using script commands.
    pass_criteria:
      - No system crash.
      - Core devices are successfully attached and detached.
    """
    iterations_number = 50

    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]

        cache_disk.create_partitions([Size(100, Unit.MebiByte)])
        core_disk.create_partitions([Size(5, Unit.GibiByte)] * 5)

        cache_part = cache_disk.partitions[0]
        core_part_list = core_disk.partitions

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part)
        cores = [cache.add_core(core_part) for core_part in core_part_list]

    for _ in TestRun.iteration(range(0, iterations_number)):
        with TestRun.step("Detach all core devices in random order"):
            random.shuffle(cores)
            for core in cores:
                casadm.detach_core(cache.cache_id, core.core_id)

        with TestRun.step("Attach all core devices in random order"):
            random.shuffle(cores)
            for core in cores:
                casadm.try_add(core.core_device, cache.cache_id, core.core_id)
