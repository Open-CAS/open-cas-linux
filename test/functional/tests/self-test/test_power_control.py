#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from core.test_run import TestRun
from test_tools.fs_tools import check_if_file_exists, read_file, remove, write_file


@pytest.mark.require_plugin("power_control")
def test_power_control_power_cycle():
    """
    title: Power control resets DUT.
    description: |
      Power cycle DUT using power control plugin and check if DUT was hard reset,
      not gracefully rebooted, and if connection to it was restored.
    pass_criteria:
      - DUT is reachable after power cycle
      - DUT boot ID changed
      - Data not written back before power cycle is lost
    """
    power_control = TestRun.plugin_manager.get_plugin("power_control")
    # /tmp may be tmpfs, the file has to be on persistent storage
    marker_path = "/var/tmp/power_control_marker"
    marker = "power control self-test"

    with TestRun.step("Read boot ID"):
        boot_id = read_file("/proc/sys/kernel/random/boot_id").strip()

    with TestRun.step("Disable periodic writeback and write file without sync"):
        TestRun.executor.run_expect_success("sysctl -w vm.dirty_writeback_centisecs=0")
        remove(marker_path, force=True)
        TestRun.executor.run_expect_success("sync")
        write_file(marker_path, marker)

    with TestRun.step("Power cycle DUT"):
        power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Check if DUT was rebooted"):
        new_boot_id = read_file("/proc/sys/kernel/random/boot_id").strip()
        if new_boot_id == boot_id:
            TestRun.fail(f"Boot ID did not change ({boot_id})")

    with TestRun.step("Check if unsynced data was lost"):
        # Graceful reboot would sync the page cache, power cycle must not
        if check_if_file_exists(marker_path) and read_file(marker_path).strip() == marker:
            TestRun.fail("Unsynced file survived power cycle, DUT was not hard reset")
        remove(marker_path, force=True)
