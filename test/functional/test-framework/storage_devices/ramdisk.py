#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath

from core.test_run import TestRun
from storage_devices.device import Device
from test_tools import disk_utils
from test_tools.fs_utils import ls, parse_ls_output
from test_utils.filesystem.symlink import Symlink
from test_utils.os_utils import reload_kernel_module, unload_kernel_module, is_kernel_module_loaded
from test_utils.size import Size, Unit


class RamDisk(Device):
    _module = "brd"

    @classmethod
    def create(cls, disk_size: Size, disk_count: int = 1):
        if disk_count < 1:
            raise ValueError("Wrong number of RAM disks requested")

        TestRun.LOGGER.info("Configure RAM disks...")
        params = {
            "rd_size": int(disk_size.get_value(Unit.KiB)),
            "rd_nr": disk_count
        }
        reload_kernel_module(cls._module, params)

        if not cls._is_configured(disk_size, disk_count):
            raise EnvironmentError(f"Wrong RAM disk configuration after loading '{cls._module}' "
                                   "module")

        return cls.list()

    @classmethod
    def remove_all(cls):
        if not is_kernel_module_loaded(cls._module):
            return

        for ram_disk in cls._list_devices():
            TestRun.executor.run(f"umount {ram_disk.full_path}")
            link_path = posixpath.join("/dev/disk/by-id", ram_disk.name)
            try:
                link = Symlink.get_symlink(link_path=link_path, target=ram_disk.full_path)
                link.remove(force=True)
            except FileNotFoundError:
                pass
        TestRun.LOGGER.info("Removing RAM disks...")
        unload_kernel_module(cls._module)

    @classmethod
    def list(cls):
        ram_disks = []
        for ram_disk in cls._list_devices():
            link_path = posixpath.join("/dev/disk/by-id", ram_disk.name)
            link = Symlink.get_symlink(
                link_path=link_path, target=ram_disk.full_path, create=True
            )
            ram_disks.append(cls(link.full_path))

        return ram_disks

    @classmethod
    def _is_configured(cls, disk_size: Size, disk_count: int):
        ram_disks = cls._list_devices()
        return (
            len(ram_disks) >= disk_count
            and Size(disk_utils.get_size(ram_disks[0].name), Unit.Byte).align_down(Unit.MiB.value)
            == disk_size.align_down(Unit.MiB.value)
        )

    @staticmethod
    def _list_devices():
        ls_ram_disks = ls("/dev/ram*")
        if "No such file or directory" in ls_ram_disks:
            return []
        return parse_ls_output(ls_ram_disks)
