#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath

from core.test_run import TestRun
from test_tools import disk_utils
from test_tools.fs_utils import check_if_file_exists, readlink
from test_utils import os_utils
from test_utils.output import CmdException


def find_disks():
    devices_result = []

    TestRun.LOGGER.info("Finding platform's disks.")

    # TODO: intelmas should be implemented as a separate tool in the future.
    #  There will be intelmas installer in case, when it is not installed
    output = TestRun.executor.run('intelmas')
    if output.exit_code != 0:
        raise Exception(f"Error while executing command: 'intelmas'.\n"
                        f"stdout: {output.stdout}\nstderr: {output.stderr}")
    block_devices = get_block_devices_list()
    try:
        discover_ssd_devices(block_devices, devices_result)
        discover_hdd_devices(block_devices, devices_result)
    except Exception as e:
        raise Exception(f"Exception occurred while looking for disks: {str(e)}")

    return devices_result


def get_block_devices_list():
    devices = TestRun.executor.run_expect_success("ls /sys/block -1").stdout.splitlines()
    os_disks = get_system_disks()
    block_devices = []

    for dev in devices:
        if ('sd' in dev or 'nvme' in dev) and dev not in os_disks:
            block_devices.append(dev)

    return block_devices


def discover_hdd_devices(block_devices, devices_res):
    for dev in block_devices:
        if TestRun.executor.run_expect_success(f"cat /sys/block/{dev}/removable").stdout == "1":
            continue  # skip removable drives
        block_size = disk_utils.get_block_size(dev)
        if int(block_size) == 4096:
            disk_type = 'hdd4k'
        else:
            disk_type = 'hdd'
        devices_res.append({
            "type": disk_type,
            "path": f"{resolve_to_by_id_link(dev)}",
            "serial": TestRun.executor.run_expect_success(
                f"sg_inq /dev/{dev} | grep -i 'serial number'"
            ).stdout.split(': ')[1].strip(),
            "blocksize": block_size,
            "size": disk_utils.get_size(dev)})
    block_devices.clear()


# This method discovers only Intel SSD devices
def discover_ssd_devices(block_devices, devices_res):
    ssd_count = int(TestRun.executor.run_expect_success(
        'intelmas show -intelssd | grep DevicePath | wc -l').stdout)
    for i in range(0, ssd_count):
        # Workaround for intelmas bug that lists all of the devices (non intel included)
        # with -intelssd flag
        if TestRun.executor.run(
                f"intelmas show -display index -intelssd {i} | grep -w Intel").exit_code == 0:
            device_path = TestRun.executor.run_expect_success(
                f"intelmas show -intelssd {i} | grep DevicePath").stdout.split()[2]
            dev = device_path.replace("/dev/", "")
            if "sg" in dev:
                sata_dev = TestRun.executor.run_expect_success(
                    f"sg_map | grep {dev}").stdout.split()[1]
                dev = sata_dev.replace("/dev/", "")
            if dev not in block_devices:
                continue
            serial_number = TestRun.executor.run_expect_success(
                f"intelmas show -intelssd {i} | grep SerialNumber").stdout.split()[2].strip()
            if 'nvme' not in device_path:
                disk_type = 'sata'
                device_path = dev
            elif TestRun.executor.run(
                    f"intelmas show -intelssd {i} | grep Optane").exit_code == 0:
                disk_type = 'optane'
            else:
                disk_type = 'nand'

            devices_res.append({
                "type": disk_type,
                "path": resolve_to_by_id_link(device_path),
                "serial": serial_number,
                "blocksize": disk_utils.get_block_size(dev),
                "size": disk_utils.get_size(dev)})
            block_devices.remove(dev)


def get_disk_serial_number(dev_path):
    commands = [
        f"(udevadm info --query=all --name={dev_path} | grep 'SCSI.*_SERIAL' || "
        f"udevadm info --query=all --name={dev_path} | grep 'ID_SERIAL_SHORT') | "
        "awk --field-separator '=' '{print $NF}'",
        f"sg_inq {dev_path} 2> /dev/null | grep '[Ss]erial number:' | "
        "awk '{print $NF}'",
        f"udevadm info --query=all --name={dev_path} | grep 'ID_SERIAL' | "
        "awk --field-separator '=' '{print $NF}'"
    ]
    for command in commands:
        serial = TestRun.executor.run(command).stdout
        if serial:
            return serial.split('\n')[0]
    return None


def get_all_serial_numbers():
    serial_numbers = {}
    block_devices = get_block_devices_list()
    for dev in block_devices:
        serial = get_disk_serial_number(dev)
        try:
            path = resolve_to_by_id_link(dev)
        except Exception:
            continue
        if serial:
            serial_numbers[serial] = path
        else:
            TestRun.LOGGER.warning(f"Device {path} ({dev}) does not have a serial number.")
            serial_numbers[path] = path
    return serial_numbers


def get_system_disks():
    system_device = TestRun.executor.run_expect_success('mount | grep " / "').stdout.split()[0]
    readlink_output = readlink(system_device)
    device_name = readlink_output.split('/')[-1]
    sys_block_path = os_utils.get_sys_block_path()
    used_device_names = __get_slaves(device_name)
    if not used_device_names:
        used_device_names = [device_name]
    disk_names = []
    for device_name in used_device_names:
        if check_if_file_exists(f'{sys_block_path}/{device_name}/partition'):
            parent_device = readlink(f'{sys_block_path}/{device_name}/..').split('/')[-1]
            disk_names.append(parent_device)
        else:
            disk_names.append(device_name)

    return disk_names


def __get_slaves(device_name: str):
    try:
        device_names = TestRun.executor.run_expect_success(
            f'ls {os_utils.get_sys_block_path()}/{device_name}/slaves').stdout.splitlines()
    except CmdException as e:
        if "No such file or directory" not in e.output.stderr:
            raise
        return None
    device_list = []
    for device_name in device_names:
        slaves = __get_slaves(device_name)
        if slaves:
            for slave in slaves:
                device_list.append(slave)
        else:
            device_list.append(device_name)
    return device_list


def resolve_to_by_id_link(path):
    by_id_paths = TestRun.executor.run_expect_success("ls /dev/disk/by-id -1").stdout.splitlines()
    dev_full_paths = [posixpath.join("/dev/disk/by-id", by_id_path) for by_id_path in by_id_paths]

    for full_path in dev_full_paths:
        # handle exception for broken links
        try:
            if readlink(full_path) == readlink(posixpath.join("/dev", path)):
                return full_path
        except CmdException:
            continue

    raise ValueError(f'By-id device link not found for device {path}')
