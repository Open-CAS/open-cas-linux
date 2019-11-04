#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
import os
import sys
import yaml
import traceback
from IPy import IP

sys.path.append(os.path.join(os.path.dirname(__file__), "../test-framework"))

from core.test_run_utils import TestRun
from api.cas import installer
from api.cas import casadm
from api.cas import git
from test_utils.os_utils import Udev
from log.logger import create_log, Log

plugins_dir = os.path.join(os.path.dirname(__file__), "../plugins")
sys.path.append(plugins_dir)
try:
    from test_wrapper import plugin as test_wrapper
except ImportError:
    pass


pytest_options = {}


@pytest.fixture(scope="session", autouse=True)
def get_pytest_options(request):
    pytest_options["remote"] = request.config.getoption("--remote")
    pytest_options["branch"] = request.config.getoption("--repo-tag")


def pytest_runtest_setup(item):
    # There should be dut config file added to config package and
    # pytest should be executed with option --dut-config=conf_name'.
    #
    # 'ip' field should be filled with valid IP string to use remote ssh executor
    # or it should be commented out when user want to execute tests on local machine
    #
    # User can also have own test wrapper, which runs test prepare, cleanup, etc.
    # Then it should be placed in plugins package

    TestRun.prepare(item)

    test_name = item.name.split('[')[0]
    TestRun.LOGGER = create_log(item.config.getoption('--log-path'), test_name)

    with TestRun.LOGGER.step("Dut prepare"):
        try:
            try:
                with open(item.config.getoption('--dut-config')) as cfg:
                    dut_config = yaml.safe_load(cfg)
            except Exception:
                dut_config = {}

            if 'test_wrapper' in sys.modules:
                if 'ip' in dut_config:
                    try:
                        IP(dut_config['ip'])
                    except ValueError:
                        raise Exception("IP address from configuration file is in invalid format.")
                dut_config = test_wrapper.prepare(dut_config)

            TestRun.setup(dut_config)

            if 'test_wrapper' in sys.modules:
                test_wrapper.try_setup_serial_log(dut_config)

            TestRun.plugins['opencas'] = {
                'repo_dir': os.path.join(os.path.dirname(__file__), "../../.."),
                'already_updated': False
            }
        except Exception as e:
            TestRun.LOGGER.exception(f"{str(e)}\n{traceback.format_exc()}")
        TestRun.LOGGER.info(f"DUT info: {TestRun.dut}")

    base_prepare(item)
    TestRun.LOGGER.write_to_command_log("Test body")
    TestRun.LOGGER.start_group("Test body")


def pytest_runtest_teardown():
    """
    This method is executed always in the end of each test, even if it fails or raises exception in
    prepare stage.
    """
    TestRun.LOGGER.end_all_groups()

    with TestRun.LOGGER.step("Cleanup after test"):
        try:
            if TestRun.executor.is_active():
                TestRun.executor.wait_for_connection()
            Udev.enable()
            unmount_cas_devices()
            casadm.stop_all_caches()
        except Exception:
            TestRun.LOGGER.warning("Exception occured during platform cleanup.")

        if 'test_wrapper' in sys.modules:
            try:
                test_wrapper.cleanup()
            except Exception as e:
                TestRun.LOGGER.warning(f"Exception occured during test wrapper cleanup.\n{str(e)}")

    TestRun.LOGGER.end()
    TestRun.LOGGER.get_additional_logs()
    Log.destroy()


def pytest_configure(config):
    TestRun.configure(config)


def pytest_addoption(parser):
    parser.addoption("--dut-config", action="store", default="None")
    parser.addoption("--log-path", action="store",
                     default=f"{os.path.join(os.path.dirname(__file__), '../results')}")
    parser.addoption("--remote", action="store", default="origin")
    parser.addoption("--repo-tag", action="store", default="master")
    parser.addoption("--force-reinstall", action="store", default="False")
    # TODO: investigate whether it is possible to pass the last param as bool


def get_remote():
    return pytest_options["remote"]


def get_branch():
    return pytest_options["branch"]


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


def kill_all_io():
    TestRun.executor.run("pkill --signal SIGKILL dd")
    TestRun.executor.run("kill -9 `ps aux | grep -i vdbench.* | awk '{ print $1 }'`")
    TestRun.executor.run("pkill --signal SIGKILL fio*")


def get_force_param(item):
    return item.config.getoption("--force-reinstall") is not "False"


def base_prepare(item):
    with TestRun.LOGGER.step("Cleanup before test"):
        Udev.enable()
        kill_all_io()

        if installer.check_if_installed():
            try:
                unmount_cas_devices()
                casadm.stop_all_caches()
            except Exception:
                pass  # TODO: Reboot DUT if test is executed remotely

        if get_force_param(item) and not TestRun.plugins['opencas']['already_updated']:
            installer.reinstall_opencas()
        elif not installer.check_if_installed():
            installer.install_opencas()
        TestRun.plugins['opencas']['already_updated'] = True
        from api.cas import init_config
        init_config.create_default_init_config()
        TestRun.LOGGER.add_build_info(f'Commit hash:')
        TestRun.LOGGER.add_build_info(f"{git.get_current_commit_hash()}")
        TestRun.LOGGER.add_build_info(f'Commit message:')
        TestRun.LOGGER.add_build_info(f'{git.get_current_commit_message()}')
