#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import casadm
from api.cas.cache_config import (CacheLineSize, CacheMode, KernelParameters,
                                  UnalignedIo, UseIoScheduler)
from api.cas.cli import get_param_cleaning_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.disk_utils import unmount
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
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
def test_fuzzy_io_class_list_cache_id(cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'get parameter' command – cache id in getting cleaning parameters.
    description:  Using Peach Fuzzer check Open CAS ability of handling wrong cache id in 'get parameter' command.
    pass_criteria:
        - System did not crash
        - Open CAS still works.
    """
    with TestRun.step("Start cache and add core device"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache, core = prepare_cas_instance(
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            cache_disk=cache_disk,
            core_disk=core_disk,
            cache_mode=CacheMode.WB,
            cache_line_size=cache_line_size,
            mount_point=mount_point,
        )
        TestRun.executor.run_expect_success("udevadm settle")

    with TestRun.step("Load example IO class configuration to instance"):
        casadm.load_io_classes(cache.cache_id, "/etc/opencas/ioclass-config.csv")

    with TestRun.step("Make filesystem on CAS device and run FIO in background"):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()

    with TestRun.step(
        "Using Peach Fuzzer and xml configuration file create 'get parameter' command and run it."
    ):
        valid_values = [str(core.cache_id).encode("ascii")]
        PeachFuzzer.generate_config(get_fuzz_config("cache_id.yml"))
        base_cmd = get_param_cleaning_cmd(cache_id="{param}").encode("ascii")
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, iterations_count)

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {iterations_count} " f"times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            run_cmd_and_validate(cmd, "Output_format", valid_values)

    with TestRun.step("Stop FIO, unmount and stop cache"):
        TestRun.executor.kill_process(fio_pid)
        unmount(core)
        cache.stop()
