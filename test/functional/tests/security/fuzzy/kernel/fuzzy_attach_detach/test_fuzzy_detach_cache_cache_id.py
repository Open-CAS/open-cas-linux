#
# Copyright(c) 2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    UnalignedIo,
    KernelParameters,
    UseIoScheduler,
)
from api.cas.cli import detach_cache_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from type_def.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    run_cmd_and_validate,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_detach_cache_cache_id(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'detach cache' command – cache id
    description: |
        Using Peach Fuzzer check ability of handling wrong cache id in 'detach cache' command.
    pass_criteria:
      - System did not crash
    """
    with TestRun.step("Create partition on cache device"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0],
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            cache_id=1,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )

    with TestRun.step("Prepare PeachFuzzer"):
        fuzz_config = get_fuzz_config("cache_id.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = detach_cache_cmd(
            cache_id="{param}"
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
                value_name="Cache id",
                is_valid=__is_valid(cmd.param),
            )
            if output.exit_code == 0:
                with TestRun.step("Attach cache"):
                    cache.attach(device=cache_disk.partitions[0], force=True)


def __is_valid(parameter):
    try:
        value = int(parameter)
    except ValueError:
        return False
    return value == 1
