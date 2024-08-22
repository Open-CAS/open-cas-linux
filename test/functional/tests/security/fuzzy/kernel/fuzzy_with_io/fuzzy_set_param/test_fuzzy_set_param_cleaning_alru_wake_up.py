#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cache_config import (
    CacheLineSize,
    CacheMode,
    KernelParameters,
    UnalignedIo,
    UseIoScheduler,
    CacheModeTrait,
)
from api.cas.cli import set_param_cleaning_alru_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    prepare_cas_instance,
    run_cmd_and_validate,
)
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import (
    get_basic_workload,
    mount_point,
)

wake_up_min = 0
wake_up_max = 3600


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_set_param_cleaning_alru_wake_up(
    cache_mode, cache_line_size, unaligned_io, use_io_scheduler
):
    """
    title: Fuzzy test for casadm 'set parameter' command for alru cleaning – wake up.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong wake up value in
        'set parameter' command for alru cleaning parameters.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """
    with TestRun.step("Start cache and add core device"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache, core = prepare_cas_instance(
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            cache_device=cache_disk,
            core_device=core_disk,
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            mount_point=mount_point,
        )

    with TestRun.step("Run FIO in background"):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()
        if not TestRun.executor.check_if_process_exists(fio_pid):
            raise Exception("Fio is not running.")

    with TestRun.step("Using Peach Fuzzer create 'set parameter' command and run it."):
        PeachFuzzer.generate_config(get_fuzz_config("uint.yml"))
        base_cmd = set_param_cleaning_alru_cmd(cache_id=str(core.cache_id), wake_up="{param}")
        commands = PeachFuzzer.get_fuzzed_command(
            command_template=base_cmd, count=TestRun.usr.fuzzy_iter_count
        )

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            if not TestRun.executor.check_if_process_exists(fio_pid):
                raise Exception("Fio is not running.")

            run_cmd_and_validate(
                cmd=cmd,
                value_name="Wake up",
                is_valid=__is_valid(cmd.param.decode("ascii", "ignore")),
            )


def __is_valid(parameter):
    try:
        value = int(parameter)
    except ValueError:
        return False
    return wake_up_min <= value <= wake_up_max
