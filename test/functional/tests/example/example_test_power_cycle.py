#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_plugin("power_control")
def test_create_example_partitions():
    """
        title: Example test doing power cycle
        description: |
          Example usage of power_control plugin.
          NOTE:
          This test uses plugin that is not included in test-framework.
          It should be provided by user as external_plugin.
        pass_criteria:
          - DUT should reboot successfully.
    """
    with TestRun.step("Power cycle DUT"):
        power_control = TestRun.plugin_manager.get_plugin('power_control')
        power_control.power_cycle()
