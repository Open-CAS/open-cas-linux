#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
import re

import pytest

from api.cas import casadm, cli_messages
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_utils.size import Size, Unit


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd]))
def test_fault_injection_core_in_raid(cache_mode):
    """
        title: Test if OpenCAS rejects using core device to build SW RAID.
        description: |
          Test if OpenCAS handles properly attempting of use core device to build SW RAID.
        pass_criteria:
          - Expected to reject RAID creation with proper warning.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(2, Unit.GibiByte)] * 2)
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]
        second_core_dev = core_disk.partitions[1]

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Attempt to use core device to build SW RAID."):
        raid_disk_1 = core_dev
        raid_disk_2 = second_core_dev

        expected_msg_1 = cli_messages.partition_not_suitable_for_array[0]
        expected_msg_2 = cli_messages.device_or_resource_busy[0]

        config = RaidConfiguration(
            level=Level.Raid1,
            metadata=MetadataVariant.Legacy,
            number_of_devices=2)

        try:
            raid = Raid.create(config, [raid_disk_1, raid_disk_2])
            TestRun.LOGGER.error(f"RAID created successfully. Expected otherwise.")
        except Exception as ex:
            output = ex.output

    with TestRun.step("Looking for any of 2 expected messages."):
        if re.search(expected_msg_1, output.stderr) or re.search(expected_msg_2, output.stderr):
            TestRun.LOGGER.info("RAID not created. Found expected warning in exception message.")
        else:
            TestRun.LOGGER.error(f"RAID not created but warning message not as expected.\n"
                                 f"Actual: '{output}'.\n"
                                 f"Expected: '{expected_msg_1}' or '{expected_msg_2}'.")
