#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import os

from api.cas.cli import casadm_bin
from core.test_run import TestRun


def test_cli_help_spelling():
    """
    title: Spelling test for 'help' command
    description: Validates spelling of 'help' in CLI
    pass criteria:
    - No spelling mistakes are found
    """

    cas_dictionary = os.path.join(TestRun.usr.repo_dir, "test", "functional", "resources")

    with TestRun.step("Run aspell"):
        TestRun.executor.rsync_to(
            f"{cas_dictionary}/",
            f"{TestRun.usr.working_dir}/",
            delete=True)
        cas_dictionary = os.path.join(TestRun.usr.working_dir, "cas_ex.en.pws")

        output = TestRun.executor.run_expect_success(
            f"{casadm_bin} -H 2>&1 | aspell list -c --lang=en_US "
            f"--add-extra-dicts={cas_dictionary}")

        if output.stdout:
            TestRun.LOGGER.error("Misspelled words found:\n")
            TestRun.LOGGER.error(output.stdout)

        output = TestRun.executor.run_expect_success(
            f"{casadm_bin} -H"
            " | awk '/Available commands:/{ cmd=1;next } /For detailed help/ { cmd=0 } "
            "cmd { print $0 }' | grep -o '\\-\\-\\S*'")
        commands = output.stdout.splitlines()

        for command in commands:
            output = TestRun.executor.run_expect_success(
                f"{casadm_bin} {command} -H | aspell list --lang=en_US "
                f"--add-extra-dicts={cas_dictionary}")

            if output.stdout:
                TestRun.LOGGER.error(f"Misspelled word found in command :{command}\n")
                TestRun.LOGGER.error(output.stdout)
