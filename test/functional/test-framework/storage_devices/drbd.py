#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
import posixpath

from core.test_run import TestRun
from storage_devices.device import Device
from test_tools.drbdadm import Drbdadm
from test_utils.filesystem.symlink import Symlink
from test_utils.output import CmdException


class Drbd(Device):
    def __init__(self, config):
        if Drbdadm.dump_config(config.name).exit_code != 0:
            raise ValueError(f"Resource {config.name} not found")
        self.config = config

    def create_metadata(self, force):
        return Drbdadm.create_metadata(self.config.name, force)

    def up(self):
        output = Drbdadm.up(self.config.name)
        if output.exit_code != 0:
            raise CmdException(f"Failed to create {self.config.name} drbd instance")

        self.path = posixpath.join("/dev/disk/by-id/", posixpath.basename(self.config.device))
        self.symlink = Symlink.get_symlink(self.path, self.config.device, True)
        self.device = Device(self.path)

        return self.device

    def wait_for_sync(self):
        return Drbdadm.wait_for_sync(self.config.name)

    def is_in_sync(self):
        return Drbdadm.in_sync(self.config.name)

    def get_status(self):
        return Drbdadm.get_status(self.config.name)

    def set_primary(self, force=False):
        return Drbdadm.set_node_primary(self.config.name, force)

    def down(self):
        output = Drbdadm.down(self.config.name)
        if output.exit_code != 0:
            raise CmdException(f"Failed to stop {self.config.name} drbd instance")

        self.device = None
        self.symlink.remove(True, True)

    @staticmethod
    def down_all():
        try:
            Drbdadm.down_all()
        except CmdException as e:
            if "no resources defined" not in str(e):
                raise e

    @staticmethod
    def is_installed():
        return TestRun.executor.run("which drbdadm && modinfo drbd").exit_code == 0
