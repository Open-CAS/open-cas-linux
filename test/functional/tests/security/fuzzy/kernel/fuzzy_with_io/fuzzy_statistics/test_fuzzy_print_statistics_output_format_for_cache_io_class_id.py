#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, CleaningPolicy, UnalignedIo, \
    KernelParameters, UseIoScheduler
from api.cas.casadm_params import OutputFormat
from api.cas.cli import print_statistics_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import get_fuzz_config, prepare_cas_instance, \
    run_cmd_and_validate
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import get_basic_workload

mount_point = "/mnt/test"
iterations_count = 1000


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_print_statistics_output_format_for_cache_io_class_id(cache_mode, cache_line_size,
                                                                    cleaning_policy, unaligned_io,
                                                                    use_io_scheduler):
    """
        title: Fuzzy test for casadm print statistics command - output format for cache IO class
        description: Using Peach Fuzzer check Open CAS ability of handling wrong CLI print
            statistics command.
        pass_criteria:
            - System did not crash
            - Open CAS still works.
    """
    with TestRun.step("Start cache with configuration and add core device, make filesystem and "
                      "mount it"):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache, core = prepare_cas_instance(cache_disk, core_disk, cache_mode, cache_line_size,
                                           KernelParameters(unaligned_io, use_io_scheduler),
                                           cleaning_policy, mount_point=mount_point)
        casadm.load_io_classes(cache.cache_id, '/etc/opencas/ioclass-config.csv')

    with TestRun.step("Run fio in background"):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [e.name.encode('ascii') for e in list(OutputFormat)]
        PeachFuzzer.generate_config(get_fuzz_config('output_format.yml'))
        base_cmd = print_statistics_cmd(cache_id=str(core.cache_id), io_class_id="0",
                                        per_io_class=True, output_format="{param}",
                                        by_id_path=False).encode('ascii')
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, iterations_count)

    for index, cmd in TestRun.iteration(enumerate(commands), f"Run command {iterations_count} "
                                                             f"times"):
        with TestRun.step(f"Iteration {index + 1}"):
            run_cmd_and_validate(cmd, "Output_format", valid_values)

    with TestRun.step("Stop 'fio'"):
        TestRun.executor.kill_process(fio_pid)
