#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import posixpath

from core.test_run import TestRun
from test_tools import disk_utils, fs_utils
from test_tools.disk_utils import get_device_filesystem_type, get_sysfs_path
from test_utils.io_stats import IoStats
from test_utils.size import Size, Unit


class Device:
    def __init__(self, path):
        disk_utils.validate_dev_path(path)
        self.path = path
        self.size = Size(disk_utils.get_size(self.get_device_id()), Unit.Byte)
        self.filesystem = get_device_filesystem_type(self.get_device_id())
        self.mount_point = None

    def create_filesystem(self, fs_type: disk_utils.Filesystem, force=True, blocksize=None):
        disk_utils.create_filesystem(self, fs_type, force, blocksize)
        self.filesystem = fs_type

    def wipe_filesystem(self, force=True):
        disk_utils.wipe_filesystem(self, force)
        self.filesystem = None

    def is_mounted(self):
        output = TestRun.executor.run(f"findmnt {self.path}")
        if output.exit_code != 0:
            return False
        else:
            mount_point_line = output.stdout.split('\n')[1]
            device_path = fs_utils.readlink(self.path)
            self.mount_point = mount_point_line[0:mount_point_line.find(device_path)].strip()
            return True

    def mount(self, mount_point, options: [str] = None):
        if not self.is_mounted():
            if disk_utils.mount(self, mount_point, options):
                self.mount_point = mount_point
        else:
            raise Exception(f"Device is already mounted! Actual mount point: {self.mount_point}")

    def unmount(self):
        if not self.is_mounted():
            TestRun.LOGGER.info("Device is not mounted.")
        elif disk_utils.unmount(self):
            self.mount_point = None

    def get_device_link(self, directory: str):
        items = self.get_all_device_links(directory)
        return next(i for i in items if i.full_path.startswith(directory))

    def get_device_id(self):
        return fs_utils.readlink(self.path).split('/')[-1]

    def get_all_device_links(self, directory: str):
        from test_tools import fs_utils
        output = fs_utils.ls(f"$(find -L {directory} -samefile {self.path})")
        return fs_utils.parse_ls_output(output, self.path)

    def get_io_stats(self):
        return IoStats.get_io_stats(self.get_device_id())

    def get_sysfs_property(self, property_name):
        path = posixpath.join(disk_utils.get_sysfs_path(self.get_device_id()),
                              "queue", property_name)
        return TestRun.executor.run_expect_success(f"cat {path}").stdout

    def set_sysfs_property(self, property_name, value):
        TestRun.LOGGER.info(
            f"Setting {property_name} for device {self.get_device_id()} to {value}.")
        path = posixpath.join(disk_utils.get_sysfs_path(self.get_device_id()), "queue",
                            property_name)
        fs_utils.write_file(path, str(value))

    def set_max_io_size(self, new_max_io_size: Size):
        self.set_sysfs_property("max_sectors_kb",
                                int(new_max_io_size.get_value(Unit.KibiByte)))

    def get_max_io_size(self):
        return Size(int(self.get_sysfs_property("max_sectors_kb")), Unit.KibiByte)

    def get_max_hw_io_size(self):
        return Size(int(self.get_sysfs_property("max_hw_sectors_kb")), Unit.KibiByte)

    def get_discard_granularity(self):
        return self.get_sysfs_property("discard_granularity")

    def get_discard_max_bytes(self):
        return self.get_sysfs_property("discard_max_bytes")

    def get_discard_zeroes_data(self):
        return self.get_sysfs_property("discard_zeroes_data")

    def get_numa_node(self):
        return int(TestRun.executor.run_expect_success(
            f"cat {get_sysfs_path(self.get_device_id())}/device/numa_node").stdout)

    def __str__(self):
        return (
            f'system path: {self.path}, short link: /dev/{self.get_device_id()},'
            f' filesystem: {self.filesystem}, mount point: {self.mount_point}, size: {self.size}'
        )

    def __repr__(self):
        return str(self)

    @staticmethod
    def get_scsi_debug_devices():
        scsi_debug_devices = TestRun.executor.run_expect_success(
            "lsscsi --scsi_id | grep scsi_debug").stdout
        return [Device(f'/dev/disk/by-id/scsi-{device.split()[-1]}')
                for device in scsi_debug_devices.splitlines()]
