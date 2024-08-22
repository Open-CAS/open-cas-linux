#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas.cli import script_try_add_cmd, remove_detached_cmd
from core.test_run import TestRun
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_device_fuzz_config,
)


def test_fuzzy_script_add_core_try_add_core_device():
    """
    title: Fuzzy test for casadm script 'add core' command - core device with try-add flag.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong core device path
        in 'add core' command with try-add flag set.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [disk.path for disk in TestRun.dut.disks]
        fuzz_config = get_device_fuzz_config(valid_values)
        valid_values = [path.encode("ascii") for path in valid_values]
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = script_try_add_cmd(
            cache_id="1", core_dev="{param}", core_id="1"
        )
        commands = PeachFuzzer.get_fuzzed_command(
            command_template=base_cmd, count=TestRun.usr.fuzzy_iter_count
        )

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Device path",
                is_valid=cmd.param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Remove core"):
                    TestRun.executor.run_expect_success(
                        remove_detached_cmd(core_device=cmd.param.decode("ascii", "ignore"))
                    )
