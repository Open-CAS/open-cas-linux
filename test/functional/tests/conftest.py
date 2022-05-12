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
from storage_devices.raid import Raid
from storage_devices.ramdisk import RamDisk
from test_utils.os_utils import Udev, kill_all_io
from test_utils.disk_finder import get_disk_serial_number
from test_tools.disk_utils import PartitionTable, create_partition_table
from test_tools.device_mapper import DeviceMapper
from test_tools.mdadm import Mdadm
from log.logger import create_log, Log
from test_utils.singleton import Singleton


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

    test_name = item.name.split('[')[0]
    TestRun.LOGGER = create_log(item.config.getoption('--log-path'), test_name)

    duts = item.config.getoption('--dut-config')
    required_duts = next(item.iter_markers(name="multidut"), None)
    required_duts = required_duts.args[0] if required_duts is not None else 1
    if required_duts > len(duts):
        raise Exception(f"Test requires {required_duts} DUTs, only {len(duts)} DUT configs "
                        f"provided")
    else:
        duts = duts[:required_duts]

    TestRun.duts = []
    for dut in duts:
        try:
            with open(dut) as cfg:
                dut_config = yaml.safe_load(cfg)
        except Exception as ex:
            raise Exception(f"{ex}\n"
                            f"You need to specify DUT config. See the example_dut_config.py file")

        dut_config['plugins_dir'] = os.path.join(os.path.dirname(__file__), "../lib")
        dut_config['opt_plugins'] = {"test_wrapper": {}, "serial_log": {}, "power_control": {}}
        dut_config['extra_logs'] = {"cas": "/var/log/opencas.log"}

        try:
            TestRun.prepare(item, dut_config)

            TestRun.presetup()
            try:
                TestRun.executor.wait_for_connection(timedelta(seconds=20))
            except paramiko.AuthenticationException:
                raise
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
        TestRun.dut.plugin_manager = TestRun.plugin_manager
        TestRun.dut.executor = TestRun.executor
        TestRun.duts.append(TestRun.dut)

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

                from storage_devices.drbd import Drbd
                if installer.check_if_installed() and Drbd.is_installed():
                    try:
                        casadm.stop_all_caches()
                    finally:
                        __drbd_cleanup()
                elif Drbd.is_installed():
                    Drbd.down_all()

                if installer.check_if_installed():
                    casadm.remove_all_detached_cores()
                    casadm.stop_all_caches()
                    from api.cas.init_config import InitConfig
                    InitConfig.create_default_init_config()
                DeviceMapper.remove_all()
                RamDisk.remove_all()
        except Exception as ex:
            TestRun.LOGGER.warning(f"Exception occurred during platform cleanup.\n"
                                   f"{str(ex)}\n{traceback.format_exc()}")

    TestRun.LOGGER.end()
    for dut in TestRun.duts:
        with TestRun.use_dut(dut):
            if TestRun.executor:
                os.makedirs(os.path.join(TestRun.LOGGER.base_dir, "dut_info", dut.ip),
                            exist_ok=True)
                TestRun.LOGGER.get_additional_logs()
    Log.destroy()
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


def __drbd_cleanup():
    from storage_devices.drbd import Drbd
    Drbd.down_all()
    # If drbd instance had been configured on top of the CAS, the previos attempt to stop
    # failed. As drbd has been stopped try to stop CAS one more time.
    if installer.check_if_installed():
        casadm.stop_all_caches()


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

        from storage_devices.drbd import Drbd
        if Drbd.is_installed():
            __drbd_cleanup()

        raids = Raid.discover()
        for raid in raids:
            # stop only those RAIDs, which are comprised of test disks
            if all(map(lambda device:
                       any(map(lambda disk_path:
                               disk_path in device.get_device_id(),
                               [bd.get_device_id() for bd in TestRun.dut.disks])),
                       raid.array_devices)):
                raid.umount_all_partitions()
                raid.remove_partitions()
                raid.stop()
                for device in raid.array_devices:
                    Mdadm.zero_superblock(os.path.join('/dev', device.get_device_id()))
                    Udev.settle()

        RamDisk.remove_all()

        for disk in TestRun.dut.disks:
            disk_serial = get_disk_serial_number(disk.path)
            if disk.serial_number != disk_serial:
                raise Exception(
                    f"Serial for {disk.path} doesn't match the one from the config."
                    f"Serial from config {disk.serial_number}, actual serial {disk_serial}"
                )

            disk.umount_all_partitions()
            Mdadm.zero_superblock(os.path.join('/dev', disk.get_device_id()))
            TestRun.executor.run_expect_success("udevadm settle")
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
