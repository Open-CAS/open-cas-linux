#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cli import script_try_add_cmd, remove_detached_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from test_utils.os_utils import Udev
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_fuzz_config,
)

cache_id_min = 1
cache_id_max = pow(2, 14)


@pytest.mark.require_disk("core", DiskTypeSet([d for d in DiskType]))
def test_fuzzy_script_add_core_try_add_cache_id():
    """
    title: Fuzzy test for casadm script 'add core' command with try-add flag - cache id.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong cache id
        in script 'add core' command with try-add flag set.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    with TestRun.step("Prepare PeachFuzzer"):
        core_disk = TestRun.disks["core"]
        fuzz_config = get_fuzz_config("cache_id.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = script_try_add_cmd(
            cache_id="{param}", core_dev=core_disk.path, core_id="1"
        )
        commands = PeachFuzzer.get_fuzzed_command(
            command_template=base_cmd, count=TestRun.usr.fuzzy_iter_count
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Cache id",
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
    return cache_id_min <= value <= cache_id_max
