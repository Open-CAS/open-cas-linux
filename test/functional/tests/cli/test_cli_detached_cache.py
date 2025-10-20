#
# Copyright(c) 2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import pytest

from api.cas import casadm, cli
from api.cas.casadm_params import OutputFormat
from api.cas.cli_messages import check_stderr_msg, set_param_detached_cache, \
    set_cache_mode_detached_cache, operation_forbidden_detached_cache, remove_core_detached_cache
from api.cas.core_config import CoreStatus
from api.cas.ioclass_config import IoClass
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.fs_tools import check_if_file_exists, remove
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_detached_cache_neg_cli_management():
    """
    title: Blocked management commands for cache in detached state
    description: |
        Try executing blocked management commands for a cache in detached state and
        check their output
    pass_criteria:
      - The execution is unsuccessful for blocked management commands
      - A proper error message is displayed for unsuccessful executions
    """

    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_disk.partitions[0]
        core_disk =  TestRun.disks["core"]
        core_disk.create_partitions([Size(800, Unit.MebiByte)])
        core_device = core_disk.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev=cache_device, force=True)
        core = cache.add_core(core_dev=core_device)

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Try to execute forbidden management commands"):
        ioclass_config_path = posixpath.join(
            TestRun.TEST_RUN_DATA_PATH, "test_ioclass_config_file.csv"
        )
        if check_if_file_exists(ioclass_config_path):
            remove(ioclass_config_path)

        random_ioclass_config = IoClass.generate_random_ioclass_list(5)
        IoClass.save_list_to_config_file(
            random_ioclass_config, ioclass_config_path=ioclass_config_path
        )

        blocked_mngt_commands = [
            (
                cli.set_param_cutoff_cmd(str(cache.cache_id), str(core.core_id), threshold="1"),
                set_param_detached_cache
            ),
            (
                cli.set_param_cutoff_cmd(str(cache.cache_id), policy="never"),
                set_param_detached_cache
            ),
            (
                cli.set_param_cleaning_cmd(str(cache.cache_id), policy="nop"),
                set_param_detached_cache
            ),
            (
                cli.set_param_cleaning_alru_cmd(str(cache.cache_id), wake_up="30"),
                set_param_detached_cache
            ),
            (
                cli.set_param_cleaning_acp_cmd(str(cache.cache_id), wake_up="100"),
                set_param_detached_cache
            ),
            (
                cli.set_param_promotion_cmd(str(cache.cache_id), policy="nhit"),
                set_param_detached_cache
            ),
            (
                cli.set_param_promotion_nhit_cmd(str(cache.cache_id), threshold="5"),
                set_param_detached_cache
            ),
            (
                cli.set_cache_mode_cmd("wb", str(cache.cache_id)),
                set_cache_mode_detached_cache
            ),
            (
                cli.script_purge_cache_cmd(str(cache.cache_id)),
                operation_forbidden_detached_cache
            ),
            (
                cli.script_purge_core_cmd(str(cache.cache_id), str(core.core_id)),
                operation_forbidden_detached_cache
            ),
            (
                cli.flush_cache_cmd(str(cache.cache_id)),
                operation_forbidden_detached_cache
            ),
            (
                cli.flush_core_cmd(str(cache.cache_id), str(core.core_id)),
                operation_forbidden_detached_cache
            ),
            (
                cli.load_io_classes_cmd(str(cache.cache_id), ioclass_config_path),
                operation_forbidden_detached_cache
            ),
        ]

        for tested_cmd, error_msg in blocked_mngt_commands:
            TestRun.LOGGER.info(f"Verify {tested_cmd}")
            output = TestRun.executor.run_expect_fail(tested_cmd)
            if not check_stderr_msg(output, error_msg):
                TestRun.LOGGER.error(
                    f'Expected the following error message "{error_msg}" '
                    f'Got "{output.stderr}" instead.'
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_detached_cache_neg_remove_core():
    """
    title: Blocking 'remove core' commands for cache in detached state
    description: |
        Try executing 'remove core' commands for a cache in detached state and
        check output and core status change
    pass_criteria:
      - The execution is unsuccessful for 'remove core' management commands
      - A proper error message is displayed for unsuccessful execution
      - 'Remove core' command results in making core inactive
    """

    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_disk.partitions[0]
        core_disk =  TestRun.disks["core"]
        core_disk.create_partitions([Size(800, Unit.MebiByte)])
        core_device = core_disk.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev=cache_device, force=True)
        core = cache.add_core(core_dev=core_device)

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Try to remove core"):
        remove_core_commands = [
            cli.script_detach_core_cmd(str(cache.cache_id), str(core.core_id)),
            cli.script_remove_core_cmd(str(cache.cache_id), str(core.core_id)),
            cli.remove_core_cmd(str(cache.cache_id), str(core.core_id)),
        ]

        for tested_cmd in remove_core_commands:
            TestRun.LOGGER.info(f"Verify {tested_cmd}")
            output = TestRun.executor.run_expect_fail(tested_cmd)
            if not check_stderr_msg(output, remove_core_detached_cache):
                TestRun.LOGGER.error(
                    f'Expected the following error message "{remove_core_detached_cache}" '
                    f'Got "{output.stderr}" instead.'
                )
            core_status = core.get_status()
            if core_status != CoreStatus.inactive:
                TestRun.LOGGER.error(f"Core should be in inactive state and it is {core_status}")
            else:
                casadm.try_add(core_device, cache.cache_id, core.core_id)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_detached_cache_permitted_cli_management():
    """
    title: Allowed management commands for cache in detached state
    description: |
        Try executing permitted management commands for a cache in detached state
    pass_criteria:
      - The execution is successful for permitted management commands
    """

    with TestRun.step("Prepare devices"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_disk.partitions[0]
        core_disk =  TestRun.disks["core"]
        core_disk.create_partitions([Size(800, Unit.MebiByte)] * 2)
        core_device = core_disk.partitions[0]
        second_core_device = core_disk.partitions[1]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev=cache_device, force=True)
        core = cache.add_core(core_dev=core_device)

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Try to execute allowed commands"):
        allowed_commands = [
            cli.get_param_cutoff_cmd(str(cache.cache_id), "1"),
            cli.get_param_cleaning_cmd(str(cache.cache_id)),
            cli.get_param_cleaning_alru_cmd(str(cache.cache_id)),
            cli.get_param_cleaning_acp_cmd(str(cache.cache_id)),
            cli.get_param_promotion_cmd(str(cache.cache_id)),
            cli.get_param_promotion_nhit_cmd(str(cache.cache_id)),
            cli.add_core_cmd(str(cache.cache_id), second_core_device.path),
            cli.list_caches_cmd(),
            cli.print_statistics_cmd(str(cache.cache_id)),
            cli.print_statistics_cmd(str(cache.cache_id), str(core.core_id)),
            cli.reset_counters_cmd(str(cache.cache_id)),
            cli.list_io_classes_cmd(str(cache.cache_id), OutputFormat.csv.name),
        ]

        for tested_cmd in allowed_commands:
            TestRun.LOGGER.info(f"Verify {tested_cmd}")
            TestRun.executor.run_expect_success(tested_cmd)

        TestRun.LOGGER.info("Trying to remove core, to make it inactive")
        TestRun.executor.run(cli.remove_core_cmd(str(cache.cache_id), str(core.core_id)))
        core_status = core.get_status()
        if core_status != CoreStatus.inactive:
            TestRun.fail(f"Core should be inactive, but it is {core_status}")
        tested_cmd = cli.remove_inactive_cmd(str(cache.cache_id), str(core.core_id))
        TestRun.LOGGER.info(f"Verify {tested_cmd}")
        TestRun.executor.run_expect_success(tested_cmd)

        tested_cmd = cli.attach_cache_cmd(cache_device.path, str(cache.cache_id))
        TestRun.LOGGER.info(f"Verify {tested_cmd}")
        TestRun.executor.run_expect_success(tested_cmd)
        TestRun.LOGGER.info("Detach cache after successfully executed attach command")
        cache.detach()

        tested_cmd = cli.stop_cmd(str(cache.cache_id))
        TestRun.LOGGER.info(f"Verify {tested_cmd}")
        TestRun.executor.run_expect_success(tested_cmd)
