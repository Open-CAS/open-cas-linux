#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cli import script_try_add_cmd, remove_detached_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_fuzz_config,
)

core_id_min = 0
core_id_max = 4095


@pytest.mark.require_disk("core", DiskTypeSet([d for d in DiskType]))
def test_fuzzy_script_add_core_try_add_core_id():
    """
    title: Fuzzy test for casadm script 'add core' command with try-add flag - core id.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong core id
        in script 'add core' command with try-add flag set.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    with TestRun.step("Prepare PeachFuzzer"):
        core_disk = TestRun.disks["core"]
        fuzz_config = get_fuzz_config("core_id.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = script_try_add_cmd(
            cache_id="1",
            core_dev=core_disk.path,
            core_id="{param}",
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
                value_name="Core id",
                is_valid=__is_valid(cmd.param),
            )
            if output.exit_code == 0:
                with TestRun.step("Remove core"):
                    TestRun.executor.run_expect_success(
                        remove_detached_cmd(core_device=core_disk.path)
                    )


def __is_valid(parameter):
    try:
        value = int(parameter)
    except ValueError:
        return False
    return core_id_min <= value <= core_id_max
