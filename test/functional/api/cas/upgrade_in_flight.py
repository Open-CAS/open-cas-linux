#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import os

from core.test_run import TestRun
from test_utils.output import CmdException


def upgrade_help(shortcut: bool = False):
    output = TestRun.executor.run(upgrade_help_cmd(shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to print upgrade help", output)


def upgrade_start():
    cmd = f"yes | {upgrade_start_cmd()}"
    TestRun.LOGGER.info(cmd)
    output = TestRun.executor.run(cmd)
    if output.exit_code != 0:
        raise CmdException("Failed to upgrade", output)

    output = TestRun.executor.run_expect_success("casadm -V")
    TestRun.LOGGER.info(f"\n{output.stdout}")


def upgrade_help_cmd(shortcut: bool = False):
    cmd = f"{_get_upgrade_script_path()} "
    cmd += "-h" if shortcut else "--help"
    return cmd


def upgrade_start_cmd():
    cmd = f"{_get_upgrade_script_path()} start"
    return cmd


def _get_upgrade_script_path():
    return os.path.join(TestRun.usr.working_dir, "utils/upgrade")
