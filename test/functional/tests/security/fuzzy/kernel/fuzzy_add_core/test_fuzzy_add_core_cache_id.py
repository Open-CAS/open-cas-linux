#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, UnalignedIo, KernelParameters, \
    UseIoScheduler, CleaningPolicy
from api.cas.cli import add_core_cmd, remove_core_cmd
from api.cas.core import Core
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import get_fuzz_config, run_cmd_and_validate


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_add_core_cache_id(cache_mode, cache_line_size, cleaning_policy, unaligned_io,
                                 use_io_scheduler):
    """
        title: Fuzzy test for casadm 'add core' command – cache id
        description: Using Peach Fuzzer check Open CAS ability of handling wrong cache id in
            'add core' command.
        pass_criteria:
            - System did not crash
            - Open CAS still works.
    """
    with TestRun.step("Start cache"):
        cache_disk = TestRun.disks['cache']
        core_disk = TestRun.disks['core']
        cache = casadm.start_cache(cache_disk, cache_mode, cache_line_size, 1, True,
                                   kernel_params=KernelParameters(unaligned_io, use_io_scheduler))
        #  Change cleaning policy to default for Write Policy different from WB
        cache.set_cleaning_policy(CleaningPolicy.DEFAULT if cache_mode != CacheMode.WB
                                  else cleaning_policy)

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [str(cache.cache_id).encode('ascii')]
        fuzz_config = get_fuzz_config("cache_id.yml")
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = add_core_cmd("{param}", core_disk.path).encode('ascii')
        commands = PeachFuzzer.get_fuzzed_command(base_cmd, TestRun.usr.fuzzy_iter_count)

    for index, cmd in TestRun.iteration(enumerate(commands),
                                        f"Run command {TestRun.usr.fuzzy_iter_count} times"):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(cmd, "Cache id", cmd.param in valid_values)
            if output.exit_code == 0:
                with TestRun.step("Remove core"):
                    core = Core(core_disk.path, cache.cache_id)
                    TestRun.executor.run_expect_success(remove_core_cmd(str(cache.cache_id),
                                                                        core.core_id))
