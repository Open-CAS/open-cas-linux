#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
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
from api.cas.cli import start_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from test_utils.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_fuzz_config,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_start_cache_line_size(cache_mode, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'start cache' command – cache line size
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong cache line size in
        'start cache' command.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    cache_id = 1

    with TestRun.step("Create partition on cache device"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Start and stop cache"):
        # Reload kernel modules
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0],
            cache_mode=cache_mode,
            cache_line_size=None,
            cache_id=cache_id,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )
        cache.stop()

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [
            str(int(e.value.get_value(Unit.KibiByte))).encode("ascii") for e in list(CacheLineSize)
        ]
        fuzz_config = get_fuzz_config("cache_line_size.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = start_cmd(
            cache_dev=cache_disk.partitions[0].path,
            cache_mode=cache_mode.name.lower(),
            cache_line_size="{param}",
            cache_id=str(cache_id),
            force=True,
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
                value_name="Cache line size",
                is_valid=cmd.param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Stop cache"):
                    casadm.stop_cache(cache_id=cache_id)
