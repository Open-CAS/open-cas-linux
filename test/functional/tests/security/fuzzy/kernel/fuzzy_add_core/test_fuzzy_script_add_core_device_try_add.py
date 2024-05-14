#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas.cli import script_try_add_cmd, remove_detached_cmd
from core.test_run import TestRun
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import run_cmd_and_validate, \
    get_device_fuzz_config


def test_fuzzy_add_core_device_try_add():
    """
        title: Fuzzy test for casadm 'add core' command - core device with try-add flag.
        description: Using Peach Fuzzer check Open CAS ability of handling wrong core device path
            in 'add core' command with try-add flag set.
        pass_criteria:
            - System did not crash
            - Open CAS still works.
    """

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [disk.path for disk in TestRun.dut.disks]
        fuzz_config = get_device_fuzz_config(valid_values)
        valid_values = [path.encode('ascii') for path in valid_values]
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = script_try_add_cmd("1", "{param}", "1").encode('ascii')
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, TestRun.usr.fuzzy_iter_count)

    for index, cmd in TestRun.iteration(enumerate(commands),
                                        f"Run command {TestRun.usr.fuzzy_iter_count} times"):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(cmd, "Device path", cmd.param in valid_values)
            if output.exit_code == 0:
                with TestRun.step("Remove core"):
                    TestRun.executor.run_expect_success(
                        remove_detached_cmd(cmd.param.decode('ascii', 'ignore')))
