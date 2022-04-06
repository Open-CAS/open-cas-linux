#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cli import casadm_bin
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit
from api.cas.cli_messages import check_stderr_msg, missing_param, disallowed_param


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_standby_neg_cli_params():
    """
    title: Verifying parameters for starting a standby cache instance
    description: |
      Try executing the standby init command with required arguments missing or
      unallowed arguments present.
    pass_criteria:
      - The execution is unsuccessful for all improper argument combinations
      - A proper error message is displayed for unsuccessful executions
    """
    with TestRun.step("Prepare the device for the cache."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]

    with TestRun.step("Prepare config for testing standby init without required params"):
        init_required_params = dict(
            [("--cache-device", cache_device.path), ("--cache-id", 5), ("--cache-line-size", 32)]
        )
        # Prepare full valid `standby init` command
        valid_cmd = casadm_bin + " --standby --init"
        for name, value in init_required_params.items():
            valid_cmd += f" {name} {value}"

    # Try to initialize standby instance with one missing param at the time
    for name, value in init_required_params.items():
        with TestRun.step(f'Try to init standby instance without "{name}" param'):
            tested_param = f"{name} {value}"
            tested_cmd = valid_cmd.replace(tested_param, "")
            output = TestRun.executor.run(tested_cmd)
            if output.exit_code == 0:
                TestRun.LOGGER.error(
                    f'"{tested_cmd}" command succeeded despite missing required "{name}" paramter!'
                )
            if not check_stderr_msg(output, missing_param) or name not in output.stderr:
                TestRun.LOGGER.error(
                    f'Expected error message in format "{missing_param[0]}" with "{name}" '
                    f'(the missing param). Got "{output.stderr}" instead.'
                )

    with TestRun.step("Prepare config for testing standby init with disallowed params"):
        init_disallowed_params = dict(
            [
                ("--core-device", "/dev/disk/by-id/core_dev_id"),
                ("--core-id", 5),
                ("--cache-mode", 32),
                ("--file", "/etc/opencas/ioclass-config.csv"),
                ("--io-class-id", "0"),
            ]
        )

    for name, value in init_disallowed_params.items():
        with TestRun.step(f'Try to init standby instance with disallowed "{name}" param'):
            tested_param = f"{name} {value}"
            tested_cmd = f"{valid_cmd} {tested_param}"
            output = TestRun.executor.run(tested_cmd)
            if output.exit_code == 0:
                TestRun.LOGGER.error(
                    f'"{tested_cmd}" command succeeded despite disallowed "{name}" paramter!'
                )
            if not check_stderr_msg(output, disallowed_param):
                TestRun.LOGGER.error(
                    f'Expected error message in format "{disallowed_param[0]}" '
                    f'Got "{output.stderr}" instead.'
                )
