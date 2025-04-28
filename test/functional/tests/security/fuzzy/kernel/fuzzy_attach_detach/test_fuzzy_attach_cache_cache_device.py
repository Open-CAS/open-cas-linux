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
from api.cas.cli import attach_cache_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from type_def.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_device_fuzz_config,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("other", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_attach_cache_cache_device(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'attach cache' command – cache device
    description: |
        Using Peach Fuzzer check ability of handling wrong device in 'attach cache' command.
    pass_criteria:
      - System did not crash
    """

    cache_id = 1

    with TestRun.step("Create partitions on all devices"):
        available_disks = [TestRun.disks["cache"], TestRun.disks["other"]]
        for disk in available_disks:
            disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Start cache"):
        cache_disk = TestRun.disks["cache"]
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0],
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            cache_id=cache_id,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Prepare PeachFuzzer"):
        disks_paths = [disk.path for disk in available_disks]
        partitions_paths = [disk.partitions[0].path for disk in available_disks]
        valid_values = disks_paths + partitions_paths
        # fuzz only partitions to speed up test
        fuzz_config = get_device_fuzz_config(partitions_paths)
        # forbidden values are created to prevent attaching other disks connected to DUT
        forbidden_values = [
            disk.path for disk in TestRun.dut.disks if disk.path not in valid_values
        ]
        valid_values = [path.encode("ascii") for path in valid_values]
        forbidden_values = [path.encode("ascii") for path in forbidden_values]

        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = attach_cache_cmd(
            cache_dev="{param}",
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
            if cmd.param in forbidden_values:
                TestRun.LOGGER.warning(
                    f"Iteration skipped due to the forbidden param value {cmd.param}."
                )
                continue
            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Device path",
                is_valid=cmd.param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Detach cache"):
                    casadm.detach_cache(cache_id)
