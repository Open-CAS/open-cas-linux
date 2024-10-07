#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import re
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
from test_utils.os_utils import Udev
from test_utils.size import Unit, Size
from tests.security.fuzzy.kernel.common.common import (
    get_fuzz_config,
    run_cmd_and_validate,
    get_cmd,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_start_cache_flags(cache_mode, cache_line_size, unaligned_io, use_io_scheduler):
    """
    title: Fuzzy test for casadm 'start cache' command – flags.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong flags in
        'start cache' command.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    cache_id = 1

    with TestRun.step("Create partition on cache device"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start and stop cache"):
        # Reload kernel modules
        cache = casadm.start_cache(
            cache_dev=cache_disk.partitions[0],
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            cache_id=cache_id,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )
        cache.stop()

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = ["", "--load", "-l", "--force", "-f"]
        fuzz_config = get_fuzz_config("flags.yml")
        PeachFuzzer.generate_config(fuzz_config)
        parameters = PeachFuzzer.generate_peach_fuzzer_parameters(TestRun.usr.fuzzy_iter_count)

    for index, parameter in TestRun.iteration(
        enumerate(parameters), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            param = parameter.decode("ascii", "ignore").rstrip()
            base_cmd = start_cmd(
                cache_dev=cache_disk.partitions[0].path,
                cache_mode=cache_mode.name.lower(),
                cache_line_size=str(int(cache_line_size.value.get_value(Unit.KibiByte))),
                cache_id=str(cache_id),
                force=True,
            )
            # --force cannot be used alongside --load param
            if param in ["--load", "-l", "--force", "-f"]:
                base_cmd = base_cmd.replace("--force", "")
            # --cache-mode, --cache-line-size, --cache-id cannot be used alongside --load param
            if param in ["--load", "-l"]:
                incompatible_params = [
                    "--cache-mode",
                    "--cache-line-size",
                    "--cache-id",
                ]
                for incompatible_param in incompatible_params:
                    any_alphanumeric_pattern = r"\w+"
                    base_cmd = re.sub(
                        pattern=f"{incompatible_param} {any_alphanumeric_pattern}",
                        repl="",
                        string=base_cmd,
                    )
            base_cmd = f"{base_cmd.strip()} {param}"

            cmd = get_cmd(base_cmd, param.encode("ascii"))

            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Flag",
                is_valid=param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Stop cache"):
                    casadm.stop_cache(cache_id=cache_id)
