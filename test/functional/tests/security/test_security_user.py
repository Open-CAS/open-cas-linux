#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, cli
from api.cas.cache_config import CacheMode
from api.cas.casadm_params import OutputFormat
from api.cas.init_config import InitConfig
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.output import CmdException
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
system_casadm_bin_path = "/sbin/casadm"
user_casadm_bin_dest_path = "/bin/casadm"
ioclass_config_path = "/etc/opencas/ioclass-config.csv"
ioclass_config_copy_path = "/etc/opencas/ioclass-config-copy.csv"
user_name = "user"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_user_cli():
    """
        title: Test that OpenCAS does not allow to change parameters in CLI by non-root user.
        description: |
          Checking if changing parameters in CLI by non-root user is forbidden by OpenCAS,
          but is permitted with 'sudo' command.
        pass_criteria:
          - Non-root user can only print help and CAS version.
          - Sudoer user is allowed to change OpenCAS parameters in CLI with sudo.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(256, Unit.MebiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(1, Unit.GibiByte), Size(256, Unit.MebiByte)])
        core_part1 = core_dev.partitions[0]
        core_part2 = core_dev.partitions[1]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, force=True)

    with TestRun.step("Add core to cache and mount it."):
        core_part1.create_filesystem(Filesystem.ext3)
        core = cache.add_core(core_part1)
        core.mount(mount_point)

    with TestRun.step(f"Copy casadm bin from {system_casadm_bin_path} "
                      f"to {user_casadm_bin_dest_path}."):
        casadm_bin = fs_utils.parse_ls_output(fs_utils.ls_item(f"{system_casadm_bin_path}"))[0]
        casadm_bin_copy = casadm_bin.copy(user_casadm_bin_dest_path, True)
        casadm_bin_copy.chmod_numerical(777)

    with TestRun.step("Copy IO class config."):
        io_conf = fs_utils.parse_ls_output(fs_utils.ls_item(f"{ioclass_config_path}"))[0]
        io_conf_copy = io_conf.copy(ioclass_config_copy_path, force=True)

    with TestRun.step("Unmount core."):
        core.unmount()

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()

    with TestRun.step("Add non-root user account."):
        TestRun.executor.run(f"useradd -N -r -l {user_name}")
        user_home_dir = fs_utils.parse_ls_output(fs_utils.ls_item(f"/home/{user_name}"))[0]
        user_home_dir.chmod_numerical(777, True)

    with TestRun.step("Try to start cache."):
        try:
            output = run_as_other_user(cli.start_cmd(cache_dev.path), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Starting cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot start cache.")

    with TestRun.step("Start cache again."):
        casadm.load_cache(cache_dev)

    with TestRun.step("Try to stop cache."):
        try:
            output = run_as_other_user(cli.stop_cmd(str(cache.cache_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Stopping cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot stop cache.")

    with TestRun.step("Try to set cache mode."):
        try:
            output = run_as_other_user(cli.set_cache_mode_cmd(CacheMode.WB,
                                                              str(cache.cache_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cache mode should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set cache mode.")

    with TestRun.step("Try to add core to cache."):
        try:
            output = run_as_other_user(cli.add_core_cmd(str(cache.cache_id),
                                                        core_part2.path), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Adding core to cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot add core.")

    with TestRun.step("Try to remove core from cache."):
        try:
            output = run_as_other_user(cli.remove_core_cmd(str(cache.cache_id),
                                                           str(core.core_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Removing core from cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot remove core.")

    with TestRun.step("Try to zero metadata."):
        try:
            output = run_as_other_user(cli.zero_metadata_cmd(str(cache_dev)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Zeroing metadata should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot zero metadata.")

    with TestRun.step("Try to list caches."):
        try:
            output = run_as_other_user(cli.list_cmd(), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Listing caches should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot list caches.")

    with TestRun.step("Try to print stats."):
        try:
            output = run_as_other_user(cli.print_statistics_cmd(str(cache.cache_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Printing stats should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot print statistics.")

    with TestRun.step("Try to reset stats."):
        try:
            output = run_as_other_user(cli.reset_counters_cmd(str(cache.cache_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Resetting stats should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot reset statistics.")

    with TestRun.step("Try to flush cache."):
        try:
            output = run_as_other_user(cli.flush_cache_cmd(str(cache.cache_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Flushing cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot flush cache.")

    with TestRun.step("Try to flush core."):
        try:
            output = run_as_other_user(cli.flush_core_cmd(str(cache.cache_id),
                                                          str(core.core_id)), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Flushing core should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot flush core.")

    with TestRun.step("Try to set cleaning policy and its parameters."):
        try:
            output = run_as_other_user(cli.set_param_cleaning_cmd(
                str(cache.cache_id), "nop"), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cleaning policy should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set cleaning policy as nop.")
        try:
            output = run_as_other_user(cli.set_param_cleaning_cmd(
                str(cache.cache_id), "alru"), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cleaning policy should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set cleaning policy as alru.")
        try:
            output = run_as_other_user(cli.set_param_cleaning_alru_cmd(str(cache.cache_id),
                                                                       "15",
                                                                       "60",
                                                                       "1000",
                                                                       "8000"), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cleaning policy parameters should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set alru cleaning policy parameters.")
        try:
            output = run_as_other_user(cli.set_param_cleaning_cmd(
                str(cache.cache_id), "acp"), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cleaning policy should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set cleaning policy as acp.")
        try:
            output = run_as_other_user(cli.set_param_cleaning_acp_cmd(str(cache.cache_id),
                                                                      "15",
                                                                      "1000"), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Setting cleaning policy parameters should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot set acp cleaning policy parameters.")

    with TestRun.step("Try to list IO class configuration."):
        try:
            output = run_as_other_user(cli.list_io_classes_cmd(
                str(cache.cache_id), OutputFormat.table.name), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Listing IO class configuration should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot list IO class configuration.")

    with TestRun.step("Try to load IO class configuration."):
        try:
            output = run_as_other_user(cli.load_io_classes_cmd(
                str(cache.cache_id), io_conf_copy), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Loading IO class configuration should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot load IO class configuration.")

    with TestRun.step("Try to print help for casadm."):
        try:
            run_as_other_user(cli.help_cmd(), user_name)
        except CmdException:
            TestRun.LOGGER.error("Non-root user should be able to print help for casadm.")

    with TestRun.step("Try to print version of OpenCAS."):
        try:
            run_as_other_user(cli.version_cmd(), user_name)
        except CmdException:
            TestRun.LOGGER.error("Non-root user should be able to print version of OpenCAS.")

    with TestRun.step("Add non-root user account to sudoers group."):
        TestRun.executor.run(f'echo "{user_name} ALL = (root) NOPASSWD:ALL" '
                             f'| sudo tee /etc/sudoers.d/{user_name}')

    with TestRun.step("Try to stop cache with 'sudo'."):
        try:
            run_as_other_user(cli.stop_cmd(str(cache.cache_id)), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to stop cache.")

    with TestRun.step("Try to start cache with 'sudo'."):
        try:
            run_as_other_user(cli.start_cmd(cache_dev.path, force=True), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to start cache.")

    with TestRun.step("Try to set cache mode with 'sudo'."):
        try:
            run_as_other_user(
                cli.set_cache_mode_cmd(str(CacheMode.WB.name).lower(), str(cache.cache_id)),
                user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to set cache mode.")

    with TestRun.step("Try to add core to cache with 'sudo'."):
        try:
            run_as_other_user(cli.add_core_cmd(str(cache.cache_id),
                                               core_part1.path), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to add core to cache.")

    with TestRun.step("Try to list caches with 'sudo'."):
        try:
            run_as_other_user(cli.list_cmd(), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to list caches.")

    with TestRun.step("Try to print stats with 'sudo'."):
        try:
            run_as_other_user(cli.print_statistics_cmd(str(cache.cache_id)), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to print stats.")

    with TestRun.step("Try to reset stats with 'sudo'."):
        try:
            run_as_other_user(cli.reset_counters_cmd(str(cache.cache_id)), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to reset stats.")

    with TestRun.step("Try to flush cache with 'sudo'."):
        try:
            run_as_other_user(cli.flush_cache_cmd(str(cache.cache_id)), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to flush cache.")

    with TestRun.step("Try to flush core with 'sudo'."):
        try:
            run_as_other_user(cli.flush_core_cmd(str(cache.cache_id),
                                                 str(core.core_id)), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to flush core.")

    with TestRun.step("Try to set cleaning policy and its parameters with 'sudo'."):
        try:
            run_as_other_user(cli.set_param_cleaning_cmd(str(cache.cache_id), "nop"),
                              user_name, True)
            run_as_other_user(cli.set_param_cleaning_cmd(str(cache.cache_id), "alru"),
                              user_name, True)
            try:
                run_as_other_user(cli.set_param_cleaning_alru_cmd(str(cache.cache_id),
                                                                  "15",
                                                                  "60",
                                                                  "1000",
                                                                  "8000"), user_name, True)
            except CmdException:
                TestRun.LOGGER.error("Non-root sudoer user should be able to "
                                     "set alru cleaning policy parameters.")
            run_as_other_user(cli.set_param_cleaning_cmd(str(cache.cache_id), "acp"),
                              user_name, True)
            try:
                run_as_other_user(cli.set_param_cleaning_acp_cmd(str(cache.cache_id),
                                                                 "15",
                                                                 "1000"), user_name, True)
            except CmdException:
                TestRun.LOGGER.error("Non-root sudoer user should be able to "
                                     "set acp cleaning policy parameters.")
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to "
                                 "set cleaning policy and its parameters.")

    with TestRun.step("Try to list IO class with 'sudo'."):
        try:
            run_as_other_user(cli.list_io_classes_cmd(str(cache.cache_id), OutputFormat.table.name),
                              user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to list IO class.")

    with TestRun.step("Try to load IO class configuration with 'sudo'."):
        try:
            run_as_other_user(cli.load_io_classes_cmd(str(cache.cache_id), io_conf_copy),
                              user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to "
                                 "load IO class configuration.")

    with TestRun.step("Try to remove core from cache with 'sudo'."):
        try:
            run_as_other_user(cli.remove_core_cmd(str(cache.cache_id), str(core.core_id)),
                              user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to remove core from cache.")

    with TestRun.step("Try to zero metadata with 'sudo'."):
        try:
            run_as_other_user(cli.zero_metadata_cmd(str(cache_dev)),
                              user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to zero metadata.")

    with TestRun.step("Try to print help for casadm with 'sudo'."):
        try:
            run_as_other_user(cli.help_cmd(), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to print help for casadm.")

    with TestRun.step("Try to print version of OpenCAS with 'sudo'."):
        try:
            run_as_other_user(cli.version_cmd(), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to print version of OpenCAS.")

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()

    with TestRun.step("Remove user account."):
        TestRun.executor.run(f"userdel -r -Z {user_name}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_user_service():
    """
        title: Test that OpenCAS does not allow to change service status by non-root user.
        description: |
          Verify that changing OpenCAS service status by non-root user is forbidden by OpenCAS.
        pass_criteria:
          - Non-root user cannot change OpenCAS service state.
          - Non-root sudoer user can change OpenCAS service state.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_dev.partitions[0]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, force=True)

    with TestRun.step("Add core to cache and mount it."):
        core_dev.create_filesystem(Filesystem.ext3)
        core = cache.add_core(core_dev)
        core.mount(mount_point)

    with TestRun.step("Create 'opencas.conf' from running configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step(f"Copy casadm bin from {system_casadm_bin_path} "
                      f"to {user_casadm_bin_dest_path}."):
        casadm_bin = fs_utils.parse_ls_output(fs_utils.ls_item(f"{system_casadm_bin_path}"))[0]
        casadm_bin_copy = casadm_bin.copy(user_casadm_bin_dest_path, True)
        casadm_bin_copy.chmod_numerical(777)

    with TestRun.step("Unmount core."):
        core.unmount()

    with TestRun.step("Add non-root user account."):
        TestRun.executor.run(f"useradd -N -r -l {user_name}")
        user_home_dir = fs_utils.parse_ls_output(fs_utils.ls_item(f"/home/{user_name}"))[0]
        user_home_dir.chmod_numerical(777, True)

    with TestRun.step("Try to stop OpenCAS service."):
        try:
            output = run_as_other_user(cli.ctl_stop(False), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Stopping OpenCAS should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot stop OpenCAS.")

    with TestRun.step("Try to start OpenCAS service."):
        try:
            output = run_as_other_user(cli.ctl_start(), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Starting OpenCAS should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot start OpenCAS.")

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()

    with TestRun.step("Try to init OpenCAS service."):
        try:
            output = run_as_other_user(cli.ctl_init(True), user_name)
            if output.exit_code == 0:
                TestRun.LOGGER.error("Initiating OpenCAS should fail!")
        except CmdException:
            TestRun.LOGGER.info("Non-root user cannot init OpenCAS.")

    with TestRun.step("Add non-root user account to sudoers group."):
        TestRun.executor.run(f'echo "{user_name} ALL = (root) NOPASSWD:ALL" '
                             f'| sudo tee /etc/sudoers.d/{user_name}')

    with TestRun.step("Try to stop OpenCAS service with 'sudo'."):
        try:
            run_as_other_user(cli.ctl_stop(False), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to stop OpenCAS.")

    with TestRun.step("Try to start OpenCAS service with 'sudo'."):
        try:
            run_as_other_user(cli.ctl_start(), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to start OpenCAS.")

    with TestRun.step("Stop caches."):
        casadm.stop_all_caches()

    with TestRun.step("Try to init OpenCAS service with 'sudo'."):
        try:
            run_as_other_user(cli.ctl_init(True), user_name, True)
        except CmdException:
            TestRun.LOGGER.error("Non-root sudoer user should be able to init OpenCAS.")

    with TestRun.step("Remove user account."):
        TestRun.executor.run(f"userdel -r -Z {user_name}")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


def run_as_other_user(command, user: str, sudo: bool = False):
    prefix = f'sudo -u {user}'
    if sudo:
        command = 'sudo ' + command
    command = f'{prefix} {command}'
    output = TestRun.executor.run(command)
    if output.exit_code != 0 or output.stderr is not "":
        raise CmdException("Must be run as root.", output)
    return output
