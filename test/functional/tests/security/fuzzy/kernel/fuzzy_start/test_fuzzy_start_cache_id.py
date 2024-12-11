#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
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
from type_def.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    run_cmd_and_validate,
)

cache_id_min = 1
cache_id_max = 16384


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_start_cache_id(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'start cache' command – cache id
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong cache id in
        'start cache' command.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """
    with TestRun.step("Create partition on cache device"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Start and stop cache"):
        # Reload kernel modules
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0],
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            cache_id=1,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )
        cache.stop()

    with TestRun.step("Prepare PeachFuzzer"):
        fuzz_config = get_fuzz_config("cache_id.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = start_cmd(
            cache_dev=cache_disk.partitions[0].path,
            cache_mode=cache_mode.name.lower(),
            cache_line_size=str(int(cache_line_size.value.get_value(Unit.KibiByte))),
            cache_id="{param}",
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
                value_name="Cache id",
                is_valid=__is_valid(cmd.param),
            )
            if output.exit_code == 0:
                with TestRun.step("Stop cache"):
                    casadm.stop_cache(cache_id=int(cmd.param))


def __is_valid(parameter):
    try:
        value = int(parameter)
    except ValueError:
        return False
    return cache_id_min <= value <= cache_id_max
