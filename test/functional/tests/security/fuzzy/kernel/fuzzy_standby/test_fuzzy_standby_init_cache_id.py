#
# Copyright(c) 2023 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas.cache_config import (
    CacheLineSize,
    KernelParameters,
    UnalignedIo,
    UseIoScheduler,
)
from test_utils.size import Unit
from api.cas.cli import standby_init_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from api.cas import casadm
from test_utils.size import Size, Unit

from tests.security.fuzzy.kernel.common.common import get_fuzz_config, run_cmd_and_validate

cache_id_range = 16385
config_file = "cache_id.yml"
iterations_count = 1000


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_standby_init_cache_id(cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'standby init' command – cache id.
    description: Using Peach Fuzzer check Intel CAS ability of handling wrong cache id
        in 'standby init' command.
    pass_criteria:
        - System did not crash,
        - Open CAS still works.
    """
    with TestRun.step("Prepare CAS instance"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(260, Unit.MebiByte)])
        cache_part = cache_disk
        cache = casadm.standby_init(
            cache_dev=cache_part,
            cache_id=1,
            cache_line_size=cache_line_size,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            force=True,
        )
        TestRun.executor.run_expect_success("udevadm settle")

    with TestRun.step("Stop cache for module reload purpose"):
        cache.stop()

    with TestRun.step("Prepare Peach fuzzer to create 'standby init' command and then run it"):
        valid_values = [str(cache_id).encode("ascii") for cache_id in range(1, cache_id_range)]
        PeachFuzzer.generate_config(get_fuzz_config("cache_id.yml"))
        base_cmd = standby_init_cmd(
            cache_dev=cache_disk.path,
            cache_line_size=str(int(cache_line_size.value.get_value(Unit.KibiByte))),
            cache_id="{param}",
            force=True,
        ).encode("ascii")
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, iterations_count)

        for index, cmd in TestRun.iteration(
            enumerate(commands), f"Run command {iterations_count} times"
        ):
            with TestRun.step(f"Iteration {index+1}"):
                is_valid = cmd.param in valid_values
                output = run_cmd_and_validate(cmd, "cache_id", is_valid)
                if output.exit_code == 0:
                    with TestRun.step("Stop cache if started successfully"):
                        casadm.stop_cache(cache_id=int(cmd.param))
