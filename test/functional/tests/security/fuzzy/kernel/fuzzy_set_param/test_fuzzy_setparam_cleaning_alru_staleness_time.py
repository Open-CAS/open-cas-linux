#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.disk_utils import unmount
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer

from api.cas.cache_config import (CacheLineSize, CacheMode, CleaningPolicy,
                                  KernelParameters, UnalignedIo,
                                  UseIoScheduler)
from api.cas.cli import set_param_cleaning_alru_cmd
from tests.security.fuzzy.kernel.common.common import (get_fuzz_config,
                                                       prepare_cas_instance,
                                                       run_cmd_and_validate)
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import \
    get_basic_workload

mount_point = "/mnt/test"
iterations_count = 1000


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_fuzzy_setparam_cleaning_alru_staleness_time(cache_line_size, unaligned_io, use_io_scheduler, cache_mode):
    """
    title: test_fuzzy_setparam_cleaning_alru_staleness_time
    description: Fuzzy test for casadm 'set parameter' command – staleness time in setting cleaning-alru parameters
    Using Peach Fuzzer check OpenCAS ability of handling wrong staleness time in 'set parameter' command.
    pass_criteria: 
        - System did not crash
        - OpenCAS still works
    """
    with TestRun.step("Start cache and add core device"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache, core = prepare_cas_instance(
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            cache_disk=cache_disk,
            core_disk=core_disk,
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            mount_point=mount_point,
        )
        TestRun.executor.run_expect_success("udevadm settle")

    with TestRun.step("Make filesystem on CAS device and run FIO in background."):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()

    with TestRun.step("Using Peach Fuzzer to create 'get parameter' command and run it."):
        valid_values = [str(x).encode("ascii") for x in range(1, 3601)]
        PeachFuzzer.generate_config(get_fuzz_config("cache_id.yml"))
        base_cmd = set_param_cleaning_alru_cmd(cache.cache_id, staleness_time="{param}").encode("ascii")
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, iterations_count)

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {iterations_count} times."
    ):

        with TestRun.step(f"Iteration {index+1}"):
            run_cmd_and_validate(cmd, "Output_format", valid_values)

    with TestRun.step("Stop FIO, unmount and stop cache"):
        TestRun.executor.kill_process(fio_pid)
        unmount(core)
        cache.stop() 
