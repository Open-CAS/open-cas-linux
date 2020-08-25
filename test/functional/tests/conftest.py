#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
import sys
from datetime import timedelta

import pytest
import yaml
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../test-framework"))

from core.test_run_utils import TestRun
from api.cas import installer
from api.cas import casadm
from api.cas import git
from test_utils.os_utils import Udev, kill_all_io
from test_tools.disk_utils import PartitionTable, create_partition_table
from test_tools.device_mapper import DeviceMapper
from log.logger import create_log, Log
from test_utils.singleton import Singleton


class Opencas(metaclass=Singleton):
    def __init__(self, repo_dir, working_dir):
        self.repo_dir = repo_dir
        self.working_dir = working_dir
        self.already_updated = False


def pytest_runtest_setup(item):
    # There should be dut config file added to config package and
    # pytest should be executed with option --dut-config=conf_name'.
    #
    # 'ip' field should be filled with valid IP string to use remote ssh executor
    # or it should be commented out when user want to execute tests on local machine
    #
    # User can also have own test wrapper, which runs test prepare, cleanup, etc.
    # Then it should be placed in plugins package

    try:
        with open(item.config.getoption('--dut-config')) as cfg:
            dut_config = yaml.safe_load(cfg)
    except Exception:
        raise Exception("You need to specify DUT config. See the example_dut_config.py file.")

    dut_config['plugins_dir'] = os.path.join(os.path.dirname(__file__), "../lib")
    dut_config['opt_plugins'] = {"test_wrapper": {}, "serial_log": {}, "power_control": {}}

    try:
        TestRun.prepare(item, dut_config)

        test_name = item.name.split('[')[0]
        TestRun.LOGGER = create_log(item.config.getoption('--log-path'), test_name)

        TestRun.presetup()
        try:
            TestRun.executor.wait_for_connection(timedelta(seconds=20))
        except Exception:
            try:
                TestRun.plugin_manager.get_plugin('power_control').power_cycle()
                TestRun.executor.wait_for_connection()
            except Exception:
                raise Exception("Failed to connect to DUT.")
        TestRun.setup()
    except Exception as ex:
        raise Exception(f"Exception occurred during test setup:\n"
                        f"{str(ex)}\n{traceback.format_exc()}")

    TestRun.usr = Opencas(
        repo_dir=os.path.join(os.path.dirname(__file__), "../../.."),
        working_dir=dut_config['working_dir'])

    TestRun.LOGGER.info(f"DUT info: {TestRun.dut}")

    base_prepare(item)
    TestRun.LOGGER.write_to_command_log("Test body")
    TestRun.LOGGER.start_group("Test body")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    res = (yield).get_result()
    TestRun.makereport(item, call, res)


def pytest_runtest_teardown():
    """
    This method is executed always in the end of each test, even if it fails or raises exception in
    prepare stage.
    """
    TestRun.LOGGER.end_all_groups()

    with TestRun.LOGGER.step("Cleanup after test"):
        try:
            if TestRun.executor:
                if not TestRun.executor.is_active():
                    TestRun.executor.wait_for_connection()
                Udev.enable()
                kill_all_io()
                unmount_cas_devices()
                if installer.check_if_installed():
                    casadm.remove_all_detached_cores()
                    casadm.stop_all_caches()
                    from api.cas.init_config import InitConfig
                    InitConfig.create_default_init_config()
                DeviceMapper.remove_all()
        except Exception as ex:
            TestRun.LOGGER.warning(f"Exception occured during platform cleanup.\n"
                                   f"{str(ex)}\n{traceback.format_exc()}")

    TestRun.LOGGER.end()
    if TestRun.executor:
        TestRun.LOGGER.get_additional_logs()
    Log.destroy()
    TestRun.teardown()


def pytest_configure(config):
    TestRun.configure(config)


def pytest_generate_tests(metafunc):
    TestRun.generate_tests(metafunc)


def pytest_addoption(parser):
    TestRun.addoption(parser)
    parser.addoption("--dut-config", action="store", default="None")
    parser.addoption("--log-path", action="store",
                     default=f"{os.path.join(os.path.dirname(__file__), '../results')}")
    parser.addoption("--force-reinstall", action="store_true", default=False)


def unmount_cas_devices():
    output = TestRun.executor.run("cat /proc/mounts | grep cas")
    # If exit code is '1' but stdout is empty, there is no mounted cas devices
    if output.exit_code == 1:
        return
    elif output.exit_code != 0:
        raise Exception(
            f"Failed to list mounted cas devices. \
            stdout: {output.stdout} \n stderr :{output.stderr}"
        )

    for line in output.stdout.splitlines():
        cas_device_path = line.split()[0]
        TestRun.LOGGER.info(f"Unmounting {cas_device_path}")
        output = TestRun.executor.run(f"umount {cas_device_path}")
        if output.exit_code != 0:
            raise Exception(
                f"Failed to unmount {cas_device_path}. \
                stdout: {output.stdout} \n stderr :{output.stderr}"
            )


def get_force_param(item):
    return item.config.getoption("--force-reinstall")


def base_prepare(item):
    with TestRun.LOGGER.step("Cleanup before test"):
        TestRun.executor.run("pkill --signal=SIGKILL fsck")
        Udev.enable()
        kill_all_io()
        DeviceMapper.remove_all()

        if installer.check_if_installed():
            try:
                from api.cas.init_config import InitConfig
                InitConfig.create_default_init_config()
                unmount_cas_devices()
                casadm.stop_all_caches()
                casadm.remove_all_detached_cores()
            except Exception:
                pass  # TODO: Reboot DUT if test is executed remotely

        for disk in TestRun.dut.disks:
            disk.umount_all_partitions()
            disk.remove_partitions()
            create_partition_table(disk, PartitionTable.gpt)

        if get_force_param(item) and not TestRun.usr.already_updated:
            installer.rsync_opencas_sources()
            installer.reinstall_opencas()
        elif not installer.check_if_installed():
            installer.rsync_opencas_sources()
            installer.set_up_opencas()
        TestRun.usr.already_updated = True
        TestRun.LOGGER.add_build_info(f'Commit hash:')
        TestRun.LOGGER.add_build_info(f"{git.get_current_commit_hash()}")
        TestRun.LOGGER.add_build_info(f'Commit message:')
        TestRun.LOGGER.add_build_info(f'{git.get_current_commit_message()}')
