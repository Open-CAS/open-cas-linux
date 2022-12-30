#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from storage_devices.disk import Disk, DiskType


class Dut:
    def __init__(self, dut_info):
        self.config = dut_info
        self.disks = []
        for disk_info in dut_info.get('disks', []):
            self.disks.append(Disk.create_disk(disk_info['path'],
                                               DiskType[disk_info['type']],
                                               disk_info.get('serial', None),
                                               disk_info['blocksize']))
        self.disks.sort(key=lambda disk: disk.disk_type, reverse=True)

        self.ipmi = dut_info['ipmi'] if 'ipmi' in dut_info else None
        self.spider = dut_info['spider'] if 'spider' in dut_info else None
        self.wps = dut_info['wps'] if 'wps' in dut_info else None
        self.env = dut_info['env'] if 'env' in dut_info else None
        self.ip = dut_info['ip'] if 'ip' in dut_info else "127.0.0.1"

    def __str__(self):
        dut_str = f'ip: {self.ip}\n'
        dut_str += f'ipmi: {self.ipmi["ip"]}\n' if self.ipmi is not None else ''
        dut_str += f'spider: {self.spider["ip"]}\n' if self.spider is not None else ''
        dut_str += f'wps: {self.wps["ip"]} port: {self.wps["port"]}\n' \
            if self.wps is not None else ''
        dut_str += f'disks:\n'
        for disk in self.disks:
            dut_str += f"\t{disk}"
        dut_str += "\n"
        return dut_str

    def get_disks_of_type(self, disk_type: DiskType):
        ret_list = []
        for d in self.disks:
            if d.disk_type == disk_type:
                ret_list.append(d)
        return ret_list
