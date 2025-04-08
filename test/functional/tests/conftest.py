#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2023-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import posixpath
import sys
import traceback
import paramiko
import pytest
import yaml

from datetime import timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), "../test-framework"))

from core.test_run import Blocked
from core.test_run_utils import TestRun
from api.cas import installer
from api.cas import casadm
from api.cas.cas_service import opencas_drop_in_directory
from storage_devices.raid import Raid
from storage_devices.ramdisk import RamDisk
from test_tools.os_tools import kill_all_io
from test_tools.udev import Udev
from test_tools.disk_tools import PartitionTable, create_partition_table
from test_tools.device_mapper import DeviceMapper
from test_tools.mdadm import Mdadm
from test_tools.fs_tools import remove, check_if_directory_exists, create_directory
from test_tools import initramfs, git
from log.logger import create_log, Log
from test_utils.common.singleton import Singleton
from storage_devices.lvm import Lvm, LvmConfiguration
from storage_devices.disk import Disk
from storage_devices.drbd import Drbd


def pytest_addoption(parser):
    TestRun.addoption(parser)
    parser.addoption("--dut-config", action="append", type=str)
    parser.addoption(
        "--log-path",
        action="store",
        default=f"{os.path.join(os.path.dirname(__file__), '../results')}",
    )
    parser.addoption("--fuzzy-iter-count", action="store")


def pytest_configure(config):
    TestRun.configure(config)


def pytest_generate_tests(metafunc):
    TestRun.generate_tests(metafunc)


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

    test_name = item.name.split("[")[0]
    TestRun.LOGGER = create_log(item.config.getoption("--log-path"), test_name)
    TestRun.LOGGER.unique_test_identifier = f"TEST__{item.name}__random_seed_{TestRun.random_seed}"

    duts = item.config.getoption("--dut-config")
    required_duts = next(item.iter_markers(name="multidut"), None)
    required_duts = required_duts.args[0] if required_duts is not None else 1
    if required_duts > len(duts):
        raise Exception(
            f"Test requires {required_duts} DUTs, only {len(duts)} DUT configs provided"
        )
    else:
        duts = duts[:required_duts]

    TestRun.duts = []
    for dut in duts:
        try:
            with open(dut) as cfg:
                dut_config = yaml.safe_load(cfg)
        except Exception as ex:
            raise Exception(
                f"{ex}\nYou need to specify DUT config. See the example_dut_config.py file"
            )

        dut_config["plugins_dir"] = os.path.join(os.path.dirname(__file__), "../lib")
        dut_config["opt_plugins"] = {"test_wrapper": {}, "serial_log": {}, "power_control": {}}
        dut_config["extra_logs"] = {"cas": "/var/log/opencas.log"}

        try:
            TestRun.prepare(item, dut_config)

            TestRun.presetup()
            try:
                TestRun.executor.wait_for_connection(timedelta(seconds=20))
            except (paramiko.AuthenticationException, Blocked):
                raise
            except Exception:
                try:
                    TestRun.plugin_manager.get_plugin("power_control").power_cycle()
                    TestRun.executor.wait_for_connection()
                except Exception:
                    raise Exception("Failed to connect to DUT.")
            TestRun.setup()
        except Exception as ex:
            raise Exception(
                f"Exception occurred during test setup:\n{str(ex)}\n{traceback.format_exc()}"
            )

        TestRun.LOGGER.print_test_identifier_to_logs()

        TestRun.usr = Opencas(
            repo_dir=os.path.join(os.path.dirname(__file__), "../../.."),
            working_dir=dut_config["working_dir"],
        )
        if item.config.getoption("--fuzzy-iter-count"):
            TestRun.usr.fuzzy_iter_count = int(item.config.getoption("--fuzzy-iter-count"))

        TestRun.LOGGER.info(f"DUT info: {TestRun.dut}")
        TestRun.dut.plugin_manager = TestRun.plugin_manager
        TestRun.dut.executor = TestRun.executor
        TestRun.dut.cache_list = []
        TestRun.dut.core_list = []
        TestRun.duts.append(TestRun.dut)

        base_prepare(item)
    TestRun.LOGGER.write_to_command_log("Test body")
    TestRun.LOGGER.start_group("Test body")


def base_prepare(item):
    with TestRun.LOGGER.step("Cleanup before test"):
        TestRun.executor.run("pkill --signal=SIGKILL fsck")
        Udev.enable()
        kill_all_io(graceful=False)
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

        remove(str(opencas_drop_in_directory), recursive=True, ignore_errors=True)

        from storage_devices.drbd import Drbd

        if Drbd.is_installed():
            __drbd_cleanup()

        lvms = Lvm.discover()
        if lvms:
            Lvm.remove_all()
        LvmConfiguration.remove_filters_from_config()
        initramfs.update()

        raids = Raid.discover()
        if len(TestRun.disks):
            test_run_disk_ids = {dev.device_id for dev in TestRun.disks.values()}
            for raid in raids:
                # stop only those RAIDs, which are comprised of test disks
                if filter(lambda dev: dev.device_id in test_run_disk_ids, raid.array_devices):
                    raid.remove_partitions()
                    raid.unmount()
                    raid.stop()
                    for device in raid.array_devices:
                        Mdadm.zero_superblock(posixpath.join("/dev", device.get_device_id()))
                        Udev.settle()

        RamDisk.remove_all()

        if check_if_directory_exists(path=TestRun.TEST_RUN_DATA_PATH):
            remove(
                path=posixpath.join(TestRun.TEST_RUN_DATA_PATH, "*"),
                force=True,
                recursive=True,
            )
        else:
            create_directory(path=TestRun.TEST_RUN_DATA_PATH)

        for disk in TestRun.disks.values():
            disk_serial = Disk.get_disk_serial_number(disk.path)
            if disk.serial_number and disk.serial_number != disk_serial:
                raise Exception(
                    f"Serial for {disk.path} doesn't match the one from the config."
                    f"Serial from config {disk.serial_number}, actual serial {disk_serial}"
                )
            disk.remove_partitions()
            disk.unmount()
            Mdadm.zero_superblock(posixpath.join("/dev", disk.get_device_id()))
            create_partition_table(disk, PartitionTable.gpt)

        TestRun.usr.already_updated = True
        TestRun.LOGGER.add_build_info(f"Commit hash:")
        TestRun.LOGGER.add_build_info(f"{git.get_current_commit_hash()}")
        TestRun.LOGGER.add_build_info(f"Commit message:")
        TestRun.LOGGER.add_build_info(f"{git.get_current_commit_message()}")


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
                kill_all_io(graceful=False)
                unmount_cas_devices()

                if installer.check_if_installed():
                    casadm.remove_all_detached_cores()
                    casadm.stop_all_caches()
                    from api.cas.init_config import InitConfig

                    InitConfig.create_default_init_config()

                from storage_devices.drbd import Drbd

                if installer.check_if_installed() and Drbd.is_installed():
                    try:
                        casadm.stop_all_caches()
                    finally:
                        __drbd_cleanup()
                elif Drbd.is_installed():
                    Drbd.down_all()

                lvms = Lvm.discover()
                if lvms:
                    Lvm.remove_all()
                LvmConfiguration.remove_filters_from_config()
                initramfs.update()

                DeviceMapper.remove_all()
                RamDisk.remove_all()

                if check_if_directory_exists(path=TestRun.TEST_RUN_DATA_PATH):
                    remove(
                        path=posixpath.join(TestRun.TEST_RUN_DATA_PATH, "*"),
                        force=True,
                        recursive=True,
                    )

        except Exception as ex:
            TestRun.LOGGER.warning(
                f"Exception occurred during platform cleanup.\n"
                f"{str(ex)}\n{traceback.format_exc()}"
            )

    TestRun.LOGGER.end()
    for dut in TestRun.duts:
        with TestRun.use_dut(dut):
            if TestRun.executor:
                os.makedirs(
                    os.path.join(
                        TestRun.LOGGER.base_dir,
                        "dut_info",
                        dut.ip if dut.ip is not None else dut.config.get("host"),
                    ),
                    exist_ok=True,
                )
                TestRun.LOGGER.get_additional_logs()
    Log.destroy()
    TestRun.teardown()


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


def __drbd_cleanup():
    Drbd.down_all()
    # If drbd instance had been configured on top of the CAS, the previous attempt to stop
    # failed. As drbd has been stopped try to stop CAS one more time.
    if installer.check_if_installed():
        casadm.stop_all_caches()

    remove("/etc/drbd.d/*.res", force=True, ignore_errors=True)


class Opencas(metaclass=Singleton):
    def __init__(self, repo_dir, working_dir):
        self.repo_dir = repo_dir
        self.working_dir = working_dir
        self.already_updated = False
        self.fuzzy_iter_count = 1000
