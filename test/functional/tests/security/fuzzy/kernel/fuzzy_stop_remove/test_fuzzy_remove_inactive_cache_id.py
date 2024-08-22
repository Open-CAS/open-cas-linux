#
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    CleaningPolicy,
    UnalignedIo,
    KernelParameters,
    UseIoScheduler,
)
from api.cas.cli import remove_inactive_cmd
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    prepare_cas_instance,
    get_fuzz_config,
    run_cmd_and_validate,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_remove_inactive_cache_id(
    cache_mode, cache_line_size, cleaning_policy, unaligned_io, use_io_scheduler
):
    """
    title: Fuzzy test for casadm 'remove inactive' command - cache id.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong cache id in
        'remove inactive' command.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """
    with TestRun.step("Start cache and add core device"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache, core = prepare_cas_instance(
            cache_device=cache_disk,
            core_device=core_disk,
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            cleaning_policy=cleaning_policy,
        )

    with TestRun.step("Create init config from running configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug core disk and load cache using created config file."):
        core_disk.unplug()
        casadm.load_cache(device=cache_disk.partitions[0])

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [str(cache.cache_id).encode("ascii")]
        PeachFuzzer.generate_config(get_fuzz_config("cache_id.yml"))
        base_cmd = remove_inactive_cmd(cache_id="{param}", core_id=str(core.core_id))
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
                is_valid=cmd.param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Reload cache with inactive core"):
                    core_disk.plug()
                    cache.add_core(core_dev=core_disk)
                    InitConfig.create_init_config_from_running_configuration()
                    cache.stop(no_data_flush=True)
                    core_disk.unplug()
                    casadm.load_cache(device=cache_disk.partitions[0])
