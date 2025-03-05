#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cli_help_messages import *
from api.cas.cli_messages import check_stderr_msg, check_stdout_msg
from core.test_run import TestRun


@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_help(shortcut):
    """
    title: Test for 'help' command.
    description: |
        Verifies that running command with 'help' param displays correct message for each
        available command.
    pass_criteria:
      - Proper help message is displayed for every command.
      - Proper help message is displayed after running command with wrong param.
    """
    check_list_cmd = [
        (" -S", " --start-cache", start_cache_help),
        (None, " --attach-cache", attach_cache_help),
        (None, " --detach-cache", detach_cache_help),
        (" -T", " --stop-cache", stop_cache_help),
        (" -X", " --set-param", set_params_help),
        (" -G", " --get-param", get_params_help),
        (" -Q", " --set-cache-mode", set_cache_mode_help),
        (" -A", " --add-core", add_core_help),
        (" -R", " --remove-core", remove_core_help),
        (None, " --remove-inactive", remove_inactive_help),
        (None, " --remove-detached", remove_detached_help),
        (" -L", " --list-caches", list_caches_help),
        (" -P", " --stats", stats_help),
        (" -Z", " --reset-counters", reset_counters_help),
        (" -F", " --flush-cache", flush_cache_help),
        (" -C", " --io-class", ioclass_help),
        (" -V", " --version", version_help),
        # (None, " --standby", standby_help),
        (" -H", " --help", help_help),
        (None, " --zero-metadata", zero_metadata_help),
    ]
    help = " -H" if shortcut else " --help"

    with TestRun.step("Run 'help' for every 'casadm' command and check output"):
        for cmds in check_list_cmd:
            cmd = cmds[0] if shortcut else cmds[1]

            if cmd:
                output = TestRun.executor.run("casadm" + cmd + help)
                check_stdout_msg(output, cmds[-1])

    with TestRun.step("Run 'help' for command that doesn`t exist and check output"):
        cmd = " -Y" if shortcut else " --yell"
        output = TestRun.executor.run("casadm" + cmd + help)
        check_stderr_msg(output, unrecognized_stderr)
        check_stdout_msg(output, unrecognized_stdout)
