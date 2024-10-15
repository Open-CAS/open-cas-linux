#
# Copyright(c) 2022 Intel Corporation
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
from api.cas.casadm_params import ParamName
from api.cas.cli import _get_param_cmd, casadm_bin
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    prepare_cas_instance,
    run_cmd_and_validate,
    get_cmd,
)
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import (
    get_basic_workload,
    mount_point,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "cache_mode",
    CacheMode.with_any_trait(CacheModeTrait.InsertRead | CacheModeTrait.InsertWrite),
)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_get_param_name(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'get parameter' command – name parameter.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong name
        in 'get parameter' command.
    pass_criteria:
      - System did not crash
      - OpenCAS still works.
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

    with TestRun.step("Make filesystem on CAS device and run FIO in background"):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()
        if not TestRun.executor.check_if_process_exists(fio_pid):
            raise Exception("Fio is not running.")

    with TestRun.step("Using Peach Fuzzer to create 'get parameter' command and run it."):
        valid_values = [e.value for e in list(ParamName)]
        PeachFuzzer.generate_config(get_fuzz_config("param_name.yml"))
        parameters = PeachFuzzer.generate_peach_fuzzer_parameters(TestRun.usr.fuzzy_iter_count)
        base_cmd = casadm_bin + _get_param_cmd(name="{param}", cache_id=str(core.cache_id))

    for index, parameter in TestRun.iteration(
        enumerate(parameters), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            if not TestRun.executor.check_if_process_exists(fio_pid):
                raise Exception("Fio is not running.")

            param = parameter.decode("ascii", "ignore").rstrip()
            cmd = base_cmd
            # for name seq-cutoff there is additional parameter required (core-id)
            if param == str(ParamName.seq_cutoff):
                cmd += f" --core-id {core.core_id}"

            cmd = cmd.replace("{param}", param)

            run_cmd_and_validate(
                cmd=get_cmd(cmd, param.encode("ascii")),
                value_name="Name",
                is_valid=param in valid_values,
            )
