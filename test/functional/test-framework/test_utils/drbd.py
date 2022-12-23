#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os

from test_utils.filesystem.file import File


class Resource:
    def __init__(self, name, device, nodes, options=None):
        self.name = name
        self.device = device
        self.nodes = nodes
        self.options = options

    def __str__(self):
        output = (
            f"resource {self.name} {{ \n"
            f"  device {self.device}; \n"
            f"{''.join([str(node) for node in self.nodes])}"
        )

        if self.options:
            output += f"  options {{\n"
            for (k, v) in self.options.items():
                output += f"    {k} {v};\n"
            output += f"  }}\n"

        output += f"}}"
        return output

    def __repr__(self):
        return str(self)

    def save(self, path="/etc/drbd.d/", filename=None):
        filename = filename if filename else f"{self.name}.res"
        file = File(path + filename)
        file.write(str(self))


class Node:
    def __init__(self, name, disk, meta_disk, ip, port):
        self.name = name
        self.disk = disk
        self.meta_disk = meta_disk
        self.ip = ip
        self.port = port

    def __str__(self):
        return (
            f"  on {self.name} {{ \n"
            f"    disk {self.disk};\n"
            f"    meta-disk {self.meta_disk};\n"
            f"    address {self.ip}:{self.port};\n"
            f"  }} \n"
        )

    def __repr__(self):
        return str(self)
