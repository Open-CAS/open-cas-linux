#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time

import pytest

from api.cas import casadm, cli, cli_messages
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.output import CmdException
from test_utils.size import Size, Unit

log_path = "/var/log/opencas.log"
wait_long_time = 180
wait_short_time = 15


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_plugin("power_control")
def test_fault_power_hit(cache_mode):
    """
        title: Test with power hit.
        description: |
          Test if there will be no metadata initialization after wake up
          - when starting cache without initialization.
        pass_criteria:
          - Start cache without re-initialization failed.
          - Start cache with load works correctly.
          - Expected message found in log.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Mark log lines for later validation of new entries."):
        last_read_line = 1
        log_lines = TestRun.executor.run_expect_success(
            f"tail -qn +{last_read_line} {log_path}").stdout.splitlines()
        last_read_line += len(log_lines)

    with TestRun.step("Hard reset."):
        power_control = TestRun.plugin_manager.get_plugin('power_control')
        power_control.power_cycle()

    with TestRun.step("Start cache without re-initialization."):
        output = TestRun.executor.run_expect_fail(cli.start_cmd(
            cache_dev=str(cache_dev.path),
            cache_mode=str(cache_mode.name.lower()),
            force=False, load=False))
        if cli_messages.check_stderr_msg(output, cli_messages.error_inserting_cache) and \
                cli_messages.check_stderr_msg(output,
                                              cli_messages.reinitialize_with_force_or_recovery):
            TestRun.LOGGER.info(f"Found expected exception: {cli_messages.error_inserting_cache}"
                                f" and {cli_messages.reinitialize_with_force_or_recovery}")

    with TestRun.step("Start cache with load."):
        try:
            cache = casadm.load_cache(cache_dev)
            TestRun.LOGGER.info(f"Cache device loaded correctly (as expected).")
        except CmdException as e:
            TestRun.LOGGER.fail(f"Failed to load cache device. Exception: {e.output}")

        time.sleep(wait_short_time)
        message_found = check_log(last_read_line, cli_messages.reinitialize_with_force_or_recovery)

        # check log second time in case that operation logging would take some more time
        if not message_found:
            time.sleep(wait_long_time)
            result = check_log(last_read_line, cli_messages.reinitialize_with_force_or_recovery)
            if not result:
                TestRun.LOGGER.fail(f"Haven't found expected message in the log.")


def check_log(last_read_line, expected_message):
    """Read recent lines in log, look for given, expected message."""
    cmd = f"tail -qn +{last_read_line} {log_path}"
    log = TestRun.executor.run(cmd)

    if cli_messages.check_stdout_msg(log, expected_message):
        TestRun.LOGGER.info(f"Found expected message in log: {expected_message}")
        return True
    else:
        TestRun.LOGGER.warning(f"Haven't found expected message in log: {expected_message}")
        return False
