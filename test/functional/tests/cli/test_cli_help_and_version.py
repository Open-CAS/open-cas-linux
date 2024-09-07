#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re

import pytest

from api.cas import casadm
from api.cas.casadm_params import OutputFormat
from api.cas.cli_help_messages import *
from api.cas.cli_messages import check_string_msg_all
from core.test_run import TestRun


@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_help(shortcut):
    """
    title: Test for 'help' command.
    description: Test if help for commands displays.
    pass_criteria:
      - Proper help displays for every command.
    """
    TestRun.LOGGER.info("Run 'help' for every 'casadm' command.")
    output = casadm.help(shortcut)
    check_string_msg_all(output.stdout, casadm_help)

    output = TestRun.executor.run("casadm" + (" -S" if shortcut else " --start-cache")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, start_cache_help)

    output = TestRun.executor.run("casadm" + (" -T" if shortcut else " --stop-cache")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, stop_cache_help)

    output = TestRun.executor.run("casadm" + (" -X" if shortcut else " --set-param")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, set_params_help)

    output = TestRun.executor.run("casadm" + (" -G" if shortcut else " --get-param")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, get_params_help)

    output = TestRun.executor.run("casadm" + (" -Q" if shortcut else " --set-cache-mode")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, set_cache_mode_help)

    output = TestRun.executor.run("casadm" + (" -A" if shortcut else " --add-core")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, add_core_help)

    output = TestRun.executor.run("casadm" + (" -R" if shortcut else " --remove-core")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, remove_core_help)

    output = TestRun.executor.run("casadm" + " --remove-detached"
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, remove_detached_help)

    output = TestRun.executor.run("casadm" + (" -L" if shortcut else " --list-caches")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, list_help)

    output = TestRun.executor.run("casadm" + (" -P" if shortcut else " --stats")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, stats_help)

    output = TestRun.executor.run("casadm" + (" -Z" if shortcut else " --reset-counters")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, reset_counters_help)

    output = TestRun.executor.run("casadm" + (" -F" if shortcut else " --flush-cache")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, flush_cache_help)

    output = TestRun.executor.run("casadm" + (" -C" if shortcut else " --io-class")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, ioclass_help)

    output = TestRun.executor.run("casadm" + (" -V" if shortcut else " --version")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, version_help)

    output = TestRun.executor.run("casadm" + (" -H" if shortcut else " --help")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, help_help)

    output = TestRun.executor.run("casadm" + " --standby"
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, standby_help)

    output = TestRun.executor.run("casadm" + " --zero-metadata"
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stdout, zero_metadata_help)

    output = TestRun.executor.run("casadm" + (" -Y" if shortcut else " --yell")
                                  + (" -H" if shortcut else " --help"))
    check_string_msg_all(output.stderr, unrecognized_stderr)
    check_string_msg_all(output.stdout, unrecognized_stdout)


@pytest.mark.parametrize("output_format", OutputFormat)
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_version(shortcut, output_format):
    """
    title: Test for 'version' command.
    description: Test if version displays.
    pass_criteria:
      - Proper OCL's components names displays in table with its versions.
    """
    TestRun.LOGGER.info("Check OCL's version.")
    output = casadm.print_version(output_format, shortcut).stdout
    TestRun.LOGGER.info(output)
    if not names_in_output(output) or not versions_in_output(output):
        TestRun.fail("'Version' command failed.")


def names_in_output(output):
    return ("CAS Cache Kernel Module" in output
            and "CAS CLI Utility" in output)


def versions_in_output(output):
    version_pattern = re.compile(r"(\d){2}\.(\d){2}\.(\d)\.(\d){4}.(\S)")
    return len(version_pattern.findall(output)) == 2
