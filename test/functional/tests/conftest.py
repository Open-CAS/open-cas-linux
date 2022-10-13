#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import sys
import traceback
from datetime import timedelta

import paramiko
import pytest
import yaml

sys.path.append(os.path.join(os.path.dirname(__file__), "../test-framework"))

from core.test_run_utils import TestRun
from api.cas import installer
from api.cas import casadm
from api.cas import git
from api.cas.cas_service import opencas_drop_in_directory
from api.cas.init_config import InitConfig
from log.logger import create_log
from test_utils.singleton import Singleton
from test_utils.output import CmdException
from test_tools.fs_utils import remove
from storage_devices.drbd import Drbd


class Opencas(metaclass=Singleton):
    def __init__(self, repo_dir, working_dir):
        self.repo_dir = repo_dir
        self.working_dir = working_dir
        self.already_updated = False


def pytest_collection_modifyitems(config, items):
    if config.option.collectonly:
        for item in items:
            multidut = next(item.iter_markers(name="multidut"), None)
            if multidut:
                number = multidut.args[0]
                print(f"multidut {item.nodeid} {number}")
                sys.stdout.flush()


def pytest_runtest_setup(item):
    # There should be dut config file added to config package and
    # pytest should be executed with option --dut-config=conf_name'.
    #
    # 'ip' field should be filled with valid IP string to use remote ssh executor
    # or it should be commented out when user want to execute tests on local machine
    #
    # User can also have own test wrapper, which runs test prepare, cleanup, etc.
    # Then it should be placed in plugins package
    duts = []
    for dut_file in item.config.getoption("--dut-config"):
        try:
            with open(dut_file) as df:
                dut_config = yaml.safe_load(df)
        except Exception as ex:
            raise Exception(
                "You need to specify DUT config. See the example_dut_config.py file"
            ) from ex

        dut_config["extra_logs"] = {"cas": "/var/log/opencas.log"}
        duts.append(dut_config)

    log_path = item.config.getoption("--log-path")
    test_name = item.name.split("[")[0]
    logger = create_log(log_path, test_name)

    TestRun.start(logger, duts, item)
    for dut in TestRun.use_all_duts():
        if not installer.check_if_installed():
            continue
        TestRun.LOGGER.info(f"CAS cleanup on {dut.ip}")
        remove(opencas_drop_in_directory, recursive=True, ignore_errors=True)

        try:
            InitConfig.create_default_init_config()
            unmount_cas_devices()
            try:
                casadm.stop_all_caches()
            except CmdException:
                TestRun.LOGGER.warning(
                    "Failed to stop all caches, will retry after stopping DRBD"
                )
            casadm.remove_all_detached_cores()
        except Exception as e:
            raise Exception("Exception occured during CAS cleanup:\n"
                            f"{str(e)}\n{traceback.format_exc()}")

        if Drbd.is_installed():
            # TODO: Need proper stacking devices teardown
            TestRun.LOGGER.workaround("Stopping DRBD")
            Drbd.down_all()

        try:
            casadm.stop_all_caches()
        except CmdException:
            TestRun.LOGGER.blocked("Failed to stop all caches")

    TestRun.prepare()

    # If some generic device was set-up on top of CAS it failed to stop, try to stop it again
    if installer.check_if_installed():
        casadm.stop_all_caches()

    TestRun.usr = Opencas(
        repo_dir=os.path.join(os.path.dirname(__file__), "../../.."),
        working_dir=TestRun.working_dir)

    cas_version = TestRun.config.get("cas_version") or git.get_current_commit_hash()
    for i, dut in enumerate(TestRun.use_all_duts()):
        if get_force_param(item) and not TestRun.usr.already_updated:
            installer.rsync_opencas_sources()
            installer.reinstall_opencas(cas_version)
        elif not installer.check_if_installed(cas_version):
            installer.rsync_opencas_sources()
            installer.set_up_opencas(cas_version)
        TestRun.LOGGER.info(f"DUT-{i} info: {dut}")

    TestRun.usr.already_updated = True

    TestRun.LOGGER.add_build_info(f'Commit hash:')
    TestRun.LOGGER.add_build_info(f"{git.get_current_commit_hash()}")
    TestRun.LOGGER.add_build_info(f'Commit message:')
    TestRun.LOGGER.add_build_info(f'{git.get_current_commit_message()}')

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
    TestRun.teardown()


def pytest_configure(config):
    TestRun.configure(config)


def pytest_generate_tests(metafunc):
    TestRun.generate_tests(metafunc)


def pytest_addoption(parser):
    TestRun.addoption(parser)
    parser.addoption("--dut-config", action="append", type=str)
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

