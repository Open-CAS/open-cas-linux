#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from test_tools import fs_utils
from test_utils import systemd


def add_mountpoint(device, mount_point, fs_type, mount_now=True):
    fs_utils.append_line("/etc/fstab",
                         f"{device.path} {mount_point} {fs_type.name} defaults 0 0")
    systemd.reload_daemon()
    if mount_now:
        systemd.restart_service("local-fs.target")


def remove_mountpoint(device):
    fs_utils.remove_lines("/etc/fstab", device.path)
    systemd.reload_daemon()
