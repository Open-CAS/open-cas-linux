#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, CleaningPolicy, UnalignedIo, \
    KernelParameters, UseIoScheduler
from api.cas.casadm_params import OutputFormat
from api.cas.cli import list_io_classes_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import get_fuzz_config, prepare_cas_instance, \
    run_cmd_and_validate

mount_point = "/mnt/test"
iterations_count = 1000


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_io_class_list_cache_id(cache_mode, cache_line_size, cleaning_policy, unaligned_io,
                                      use_io_scheduler):
    """
        title: Fuzzy test for casadm list IO class command – cache id
        description: Using Peach Fuzzer check Open CAS ability of handling wrong cache id in
            ‘list IO class’ command.
        pass_criteria:
            - System did not crash
            - Open CAS still works.
    """
    with TestRun.step("Start cache and add core device"):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache, core = prepare_cas_instance(cache_disk, core_disk, cache_mode, cache_line_size,
                                           KernelParameters(unaligned_io, use_io_scheduler),
                                           cleaning_policy)

    with TestRun.step("Load default IO class configuration file"):
        casadm.load_io_classes(cache.cache_id, '/etc/opencas/ioclass-config.csv')

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [str(core.cache_id).encode('ascii')]
        PeachFuzzer.generate_config(get_fuzz_config("cache_id.yml"))
        base_cmd = list_io_classes_cmd("{param}", OutputFormat.table.name).encode('ascii')
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, iterations_count)

    for index, cmd in TestRun.iteration(enumerate(commands), f"Run command {iterations_count} "
                                                             f"times"):
        with TestRun.step(f"Iteration {index + 1}"):
            run_cmd_and_validate(cmd, "Cache_id", valid_values)
