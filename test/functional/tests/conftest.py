#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
import os
import sys
import yaml
from IPy import IP
sys.path.append(os.path.join(os.path.dirname(__file__), "../test-framework"))

from core.test_run_utils import TestRun
from api.cas import installer
from api.cas import casadm
from test_utils.os_utils import Udev


# TODO: Provide basic plugin subsystem
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
    pytest_options["force_reinstall"] = request.config.getoption("--force-reinstall")


@pytest.fixture()
def prepare_and_cleanup(request):
    """
    This fixture returns the dictionary, which contains DUT ip, IPMI, spider, list of disks.
    This fixture also returns the executor of commands
    """

    # There should be dut config file added to config package and
    # pytest should be executed with option --dut-config=conf_name'.
    #
    # 'ip' field should be filled with valid IP string to use remote ssh executor
    # or it should be commented out when user want to execute tests on local machine
    #
    # User can also have own test wrapper, which runs test prepare, cleanup, etc.
    # Then in the config/configuration.py file there should be added path to it:
    # test_wrapper_dir = 'wrapper_path'

    try:
        with open(request.config.getoption('--dut-config')) as cfg:
            dut_config = yaml.safe_load(cfg)
    except Exception:
        dut_config = {}

    if 'test_wrapper' in sys.modules:
        if 'ip' in dut_config:
            try:
                IP(dut_config['ip'])
            except ValueError:
                raise Exception("IP address from configuration file is in invalid format.")
        dut_config = test_wrapper.prepare(request.param, dut_config)

    TestRun.prepare(dut_config)

    TestRun.plugins['opencas'] = {'already_updated': False}

    TestRun.LOGGER.info(f"**********Test {request.node.name} started!**********")
    yield

    TestRun.LOGGER.info("Test cleanup")
    Udev.enable()
    unmount_cas_devices()
    casadm.stop_all_caches()
    if 'test_wrapper' in sys.modules:
        test_wrapper.cleanup()


def pytest_addoption(parser):
    parser.addoption("--dut-config", action="store", default="None")
    parser.addoption("--remote", action="store", default="origin")
    parser.addoption("--repo-tag", action="store", default="master")
    parser.addoption("--force-reinstall", action="store", default="False")
    # TODO: investigate whether it is possible to pass the last param as bool


def get_remote():
    return pytest_options["remote"]


def get_branch():
    return pytest_options["branch"]


def get_force_param():
    return pytest_options["force_reinstall"]


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


def base_prepare():
    TestRun.LOGGER.info("Base test prepare")
    TestRun.LOGGER.info(f"DUT info: {TestRun.dut}")

    Udev.enable()

    kill_all_io()

    if installer.check_if_installed():
        try:
            unmount_cas_devices()
            casadm.stop_all_caches()
        except Exception:
            pass  # TODO: Reboot DUT if test is executed remotely

    if get_force_param() is not "False" and not TestRun.plugins['opencas']['already_updated']:
        installer.reinstall_opencas()
    elif not installer.check_if_installed():
        installer.install_opencas()
    TestRun.plugins['opencas']['already_updated'] = True
