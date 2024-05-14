#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, UnalignedIo, KernelParameters, \
    UseIoScheduler
from api.cas.cli import stop_cmd, start_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from test_utils.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import run_cmd_and_validate, \
    get_device_fuzz_config


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_start_cache_device(cache_mode, cache_line_size, unaligned_io,
                                  use_io_scheduler):
    """
        title: Fuzzy test for casadm 'start cache' command – cache device
        description: Using Peach Fuzzer check Open CAS ability of handling wrong device id in
            'start cache' command.
        pass_criteria:
            - System did not crash
            - Open CAS still works.
    """
    with TestRun.step("Create 400MiB partitions on all devices"):
        for disk in TestRun.dut.disks:
            disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Start and stop cache"):
        cache_disk = TestRun.disks['cache']
        # Reload kernel modules
        cache = casadm.start_cache(cache_disk.partitions[0], cache_mode, cache_line_size, 1, True,
                                   kernel_params=KernelParameters(unaligned_io, use_io_scheduler))
        cache.stop()

    with TestRun.step("Prepare PeachFuzzer"):
        disks_paths = [disk.path for disk in TestRun.dut.disks]
        partitions_paths = [disk.partitions[0].path for disk in TestRun.dut.disks]
        valid_values = disks_paths + partitions_paths
        # fuzz only partitions to speed up test
        fuzz_config = get_device_fuzz_config(partitions_paths)
        valid_values = [path.encode('ascii') for path in valid_values]
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = start_cmd("{param}", cache_mode.name.lower(),
                             str(int(cache_line_size.value.get_value(Unit.KibiByte))), "1",
                             force=True).encode('ascii')
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, TestRun.usr.fuzzy_iter_count)

    for index, cmd in TestRun.iteration(enumerate(commands),
                                        f"Run command {TestRun.usr.fuzzy_iter_count} times"):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(cmd, "Device path", cmd.param in valid_values)
            if output.exit_code == 0:
                with TestRun.step("Stop cache"):
                    TestRun.executor.run_expect_success(stop_cmd("1"))
