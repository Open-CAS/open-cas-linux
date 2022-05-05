#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cli import casadm_bin, standby_activate_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit
from api.cas.cli_messages import (
    check_stderr_msg,
    missing_param,
    disallowed_param,
    operation_forbiden_in_standby,
    mutually_exclusive_params_init,
    mutually_exclusive_params_load, activate_without_detach,
)
from api.cas.cache_config import CacheLineSize, CacheStatus
from api.cas import cli
from api.cas.ioclass_config import IoClass


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


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_activate_neg_cli_params():
    """
    title: Verifying parameters for activating a standby cache instance.
    description: |
        Try executing the standby activate command with required arguments missing or unallowed
        arguments present.
    pass_criteria:
        -The execution is unsuccessful for all improper argument combinations
        -A proper error message is displayed for unsuccessful executions
    """
    with TestRun.step("Prepare the device for the cache."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        cache_id = 1
        cache_line_size = 32

    with TestRun.step("Init standby cache"):
        cache_dev = Device(cache_device.path)
        cache = standby_init(
            cache_dev=cache_dev, cache_id=cache_id, cache_line_size=cache_line_size, force=True
        )

    with TestRun.step("Detach standby cache"):
        cache.standby_detach()

    # Test standby activate
    with TestRun.step("Prepare config for testing standby activate with required params"):
        standby_activate_required_params = dict(
            [("--cache-device", cache_device.path), ("--cache-id", cache_id)]
        )
        # Prepare full valid `standby activate` command
        valid_cmd = casadm_bin + " --standby --activate"
        for name, value in standby_activate_required_params.items():
            valid_cmd += f" {name} {value}"

        for name, value in standby_activate_required_params.items():
            with TestRun.step(f'Try to standby activate instance without "{name}" param'):
                tested_param = f"{name} {value}"
                tested_cmd = valid_cmd.replace(tested_param, "")
                output = TestRun.executor.run(tested_cmd)
                if output.exit_code == 0:
                    TestRun.LOGGER.error(
                        f'"{tested_cmd}" command succeeded despite missing obligatory'
                        f' "{name}" paramter!'
                    )
                if not check_stderr_msg(output, missing_param) or name not in output.stderr:
                    TestRun.LOGGER.error(
                        f'Expected error message in format "{missing_param[0]}" with "{name}" '
                        f'(the missing param). Got "{output.stderr}" instead.'
                    )

    with TestRun.step("Prepare config for testing standby activate with disallowed params"):
        activate_disallowed_params = dict(
            [
                ("--core-device", "/dev/disk/by-id/core_dev_id"),
                ("--core-id", 5),
                ("--cache-mode", 32),
                ("--file", "/etc/opencas/ioclass-config.csv"),
                ("--io-class-id", "0"),
                ("--cache-line-size", 32),
            ]
        )

    for name, value in activate_disallowed_params.items():
        with TestRun.step(f'Try to activate standby instance with disallowed "{name}" param'):
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


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_standby_neg_cli_management():
    """
    title: Blocking management commands in standby state
    description: |
      Try executing management commands for a cache in standby state
    pass_criteria:
      - The execution is unsuccessful for blocked management commands
      - The execution is successful for allowed management commands
      - A proper error message is displayed for unsuccessful executions
    """
    with TestRun.step("Prepare the device for the cache."):
        device = TestRun.disks["cache"]
        device.create_partitions([Size(500, Unit.MebiByte), Size(500, Unit.MebiByte)])
        cache_device = device.partitions[0]
        core_device = device.partitions[1]

    with TestRun.step("Prepare the standby instance"):
        cache_id = 1
        cache = casadm.standby_init(
            cache_dev=cache_device, cache_id=cache_id, cache_line_size=32, force=True
        )

        ioclass_config_path = "/tmp/standby_cli_neg_mngt_test_ioclass_config_file.csv"
        TestRun.executor.run(f"rm -rf {ioclass_config_path}")
        random_ioclass_config = IoClass.generate_random_ioclass_list(5)
        IoClass.save_list_to_config_file(
            random_ioclass_config, ioclass_config_path=ioclass_config_path
        )

        blocked_mngt_commands = [
            cli.get_param_cutoff_cmd(str(cache_id), "1"),
            cli.get_param_cleaning_cmd(str(cache_id)),
            cli.get_param_cleaning_alru_cmd(str(cache_id)),
            cli.get_param_cleaning_acp_cmd(str(cache_id)),
            cli.set_param_cutoff_cmd(str(cache_id), "1", threshold="1"),
            cli.set_param_cutoff_cmd(str(cache_id), policy="never"),
            cli.set_param_cleaning_cmd(str(cache_id), policy="nop"),
            cli.set_param_cleaning_alru_cmd(str(cache_id), wake_up="30"),
            cli.set_param_cleaning_acp_cmd(str(cache_id), wake_up="100"),
            cli.set_param_promotion_cmd(str(cache_id), policy="nhit"),
            cli.set_param_promotion_nhit_cmd(str(cache_id), threshold="5"),
            cli.set_cache_mode_cmd("wb", str(cache_id)),
            cli.add_core_cmd(str(cache_id), core_device.path),
            cli.remove_core_cmd(str(cache_id), "1"),
            cli.remove_inactive_cmd(str(cache_id), "1"),
            cli.reset_counters_cmd(str(cache_id)),
            cli.flush_cache_cmd(str(cache_id)),
            cli.flush_core_cmd(str(cache_id), "1"),
            cli.load_io_classes_cmd(str(cache_id), ioclass_config_path),
            cli.list_io_classes_cmd(str(cache_id), output_format="csv"),
            cli.script_try_add_cmd(str(cache_id), core_device.path, core_id=1),
            cli.script_purge_cache_cmd(str(cache_id)),
            cli.script_purge_core_cmd(str(cache_id), "1"),
            cli.script_detach_core_cmd(str(cache_id), "1"),
            cli.script_remove_core_cmd(str(cache_id), "1"),
        ]

    with TestRun.step("Try to execute forbidden management commands in standby mode"):
        for cmd in blocked_mngt_commands:

            TestRun.LOGGER.info(f"Verify {cmd}")
            output = TestRun.executor.run_expect_fail(cmd)
            if not check_stderr_msg(output, operation_forbiden_in_standby):
                TestRun.LOGGER.error(
                    f'Expected the following error message "{operation_forbiden_in_standby[0]}" '
                    f'Got "{output.stderr}" instead.'
                )

    with TestRun.step("Stop the standby instance"):
        TestRun.executor.run(f"rm -rf {ioclass_config_path}")
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_start_neg_cli_flags():
    """
    title: Blocking standby start command with mutually exclusive flags
    description: |
       Try executing the standby start command with different combinations of mutually
       exclusive flags.
    pass_criteria:
      - The command execution is unsuccessful for commands with mutually exclusive flags
      - A proper error message is displayed
    """

    with TestRun.step("Prepare the device for the cache."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        cache_id = 1
        cache_line_size = 32

    with TestRun.step("Try to start standby cache with mutually exclusive parameters"):
        init_required_params = f' --cache-device {cache_device.path}' \
                               f' --cache-id {cache_id}' \
                               f' --cache-line-size {cache_line_size}'

        mutually_exclusive_cmd_init = f"{casadm_bin} --standby --init --load" \
                                      f" {init_required_params}"
        output = TestRun.executor.run_expect_fail(mutually_exclusive_cmd_init)
        if not check_stderr_msg(output, mutually_exclusive_params_init):
            TestRun.LOGGER.error(
                f'Expected error message in format '
                f'"{mutually_exclusive_params_init[0]}"'
                f'Got "{output.stderr}" instead.'
            )

        mutually_exclusive_cmd_load = [
            f"{casadm_bin} --standby --load --cache-device {cache_device.path}"
            f" --cache-id {cache_id}",
            f"{casadm_bin} --standby --load --cache-device {cache_device.path}"
            f" --cache-line-size {cache_line_size}",
            f"{casadm_bin} --standby --load --cache-device {cache_device.path}"
            f" --force"
        ]

        for cmd in mutually_exclusive_cmd_load:
            output = TestRun.executor.run_expect_fail(cmd)
            if not check_stderr_msg(output, mutually_exclusive_params_load):
                TestRun.LOGGER.error(
                    f'Expected error message in format '
                    f'"{mutually_exclusive_params_load[0]}"'
                    f'Got "{output.stderr}" instead.'
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
def test_activate_without_detach():
    """
    title: Activate cache without detach command.
    description: |
       Try activate passive cache without detach command before activation.
    pass_criteria:
      - The activation is not possible
      - The cache remains in Standby state after unsuccessful activation
      - The cache exported object is present after an unsuccessful activation
    """

    with TestRun.step("Prepare the device for the cache."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(500, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        cache_id = 1
        cache_exp_obj_name = f"cas-cache-{cache_id}"

    with TestRun.step("Start cache instance."):
        cache = casadm.start_cache(cache_dev=cache_dev, cache_id=cache_id)

    with TestRun.step("Stop cache instance."):
        cache.stop()

    with TestRun.step("Load standby cache instance."):
        casadm.standby_load(cache_dev=cache_dev)

    with TestRun.step("Verify if the cache exported object appeared in the system"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep {cache_exp_obj_name}")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")

    with TestRun.step("Try to activate cache instance"):
        cmd = f"{casadm_bin} --standby --activate --cache-id {cache_id} --cache-device " \
              f"{cache_dev.path}"
        output = TestRun.executor.run(cmd)
        if not check_stderr_msg(output, activate_without_detach):
            TestRun.LOGGER.error(
                f'Expected error message in format '
                f'"{activate_without_detach[0]}"'
                f'Got "{output.stderr}" instead.'
            )

    with TestRun.step("Verify if cache is in standby state after failed activation"):
        caches = casadm_parser.get_caches()
        if len(caches) < 1:
            TestRun.LOGGER.error(f'Cache not present in system')
        else:
            cache_status = caches[0].get_status()
            if cache_status != CacheStatus.standby:
                TestRun.LOGGER.error(
                    f'Expected Cache state: "{CacheStatus.standby.value}" '
                    f'Got "{cache_status.value}" instead.'
                )

    with TestRun.step("Verify if the cache exported object remains in the system"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep {cache_exp_obj_name}")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")
