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
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from test_tools.udev import Udev
from type_def.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    run_cmd_and_validate,
    get_cmd,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_attach_cache_flags(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'attach cache' command – flags.
    description: |
        Using Peach Fuzzer check ability of handling wrong flags in 'attach cache' command.
    pass_criteria:
      - System did not crash
    """

    cache_id = 1

    with TestRun.step("Create partition on cache device"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache"):
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
        valid_values = ["", "--force", "-f"]
        fuzz_config = get_fuzz_config("flags.yml")
        PeachFuzzer.generate_config(fuzz_config)
        parameters = PeachFuzzer.generate_peach_fuzzer_parameters(TestRun.usr.fuzzy_iter_count)

    for index, parameter in TestRun.iteration(
        enumerate(parameters), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            param = parameter.decode("ascii", "ignore").rstrip()
            base_cmd = attach_cache_cmd(
                cache_dev=cache_disk.partitions[0].path,
                cache_id=str(cache_id),
                force=False,
            )

            base_cmd = f"{base_cmd.strip()} {param}"

            cmd = get_cmd(base_cmd, param.encode("ascii"))

            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Flag",
                is_valid=param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Detach cache"):
                    casadm.detach_cache(cache_id=cache_id)
