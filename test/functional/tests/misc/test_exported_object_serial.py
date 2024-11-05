#
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import itertools
import os
import random
import pytest

from api.cas import casadm
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from type_def.size import Size, Unit

serial_template = "opencas-"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_exported_object_serial():
    """
    title: Cached volume serial creation.
    description: Validate if each exported object is created with proper serial.
    pass_criteria:
      - Each exported object has proper serial in following format:
        opencas-casX-Y where X is cache ID and Y is core ID
      - serial is not changed after system reboot
    """
    caches_count = 4
    cores_count = [random.randint(1, 4) for _ in range(caches_count)]

    with TestRun.step("Prepare devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(1, Unit.GibiByte)] * caches_count)
        core_dev.create_partitions([Size(1, Unit.GibiByte)] * sum(cores_count))

    with TestRun.step("Start caches and add cores"):
        caches = [
            casadm.start_cache(cache_dev.partitions[cache_num], force=True)
            for cache_num in range(caches_count)
        ]

        part_iter = iter(core_dev.partitions)
        cores_per_cache = [
            [
                caches[cache_num].add_core(next(part_iter))
                for _ in range(cores_count[cache_num])
            ] for cache_num in range(caches_count)
        ]
        cores = list(itertools.chain(*cores_per_cache))

    with TestRun.step("Check if each cached volume has proper serial"):
        check_serial(cores)

    with TestRun.step("Create init config from running configuration"):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot platform"):
        TestRun.executor.reboot()

    with TestRun.step("Check if cached volumes have proper serial after reboot"):
        check_serial(cores)


def check_serial(cores):
    for core in cores:
        serial = core.get_serial()
        if serial != serial_template + os.path.basename(core.path):
            TestRun.LOGGER.error(f"Cached volume {core.path} has wrong serial: '{serial}'")
