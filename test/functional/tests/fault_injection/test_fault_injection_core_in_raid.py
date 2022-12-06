#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_utils.size import Size, Unit
from api.cas.cli_messages import (
    mdadm_partition_not_suitable_for_array,
    mdadm_device_or_resource_busy,
    check_string_msg_any,
)

expected_msg_1 = mdadm_partition_not_suitable_for_array
expected_msg_2 = mdadm_device_or_resource_busy


@pytest.mark.parametrizex("cache_mode", [CacheMode.WB, CacheMode.WT])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd]))
@pytest.mark.require_disk("core2", DiskTypeSet([DiskType.sata, DiskType.hdd]))
def test_fault_injection_core_in_raid(cache_mode):
    """
    title: Try to create raid on device used as a core device
    description: Verify that it is impossible to use an underlying core disk as raid member
    pass_criteria:
      - Expected to reject RAID creation with proper warning.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks["cache"]
        first_core_disk = TestRun.disks["core"]
        second_core_disk = TestRun.disks["core2"]
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        first_core_disk.create_partitions([Size(2, Unit.GibiByte)])
        second_core_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        first_core_dev = first_core_disk.partitions[0]
        second_core_dev = second_core_disk.partitions[0]

    with TestRun.step("Start cas and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        casadm.add_core(cache, first_core_dev)

    with TestRun.step("Attempt to use core device to build SW RAID."):
        config = RaidConfiguration(
            level=Level.Raid1, metadata=MetadataVariant.Legacy, number_of_devices=2
        )

        try:
            Raid.create(config, [first_core_dev, second_core_dev])
            TestRun.fail(f"RAID created successfully. Expected otherwise.")
        except Exception as ex:
            output = ex.output.stderr

    with TestRun.step("Looking for any of 2 expected messages."):

        if check_string_msg_any(output, expected_msg_1 + expected_msg_2):
            TestRun.LOGGER.info("RAID not created. Found expected warning in exception message.")
        else:
            TestRun.LOGGER.error(f"RAID not created but warning message not as expected.\n")