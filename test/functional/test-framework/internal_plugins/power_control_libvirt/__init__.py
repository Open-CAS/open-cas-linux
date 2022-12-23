#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from datetime import timedelta

from connection.local_executor import LocalExecutor
from connection.ssh_executor import SshExecutor
from core.test_run import TestRun


class PowerControlPlugin:
    def __init__(self, params, config):
        print("Power Control LibVirt Plugin initialization")
        try:
            self.ip = config['ip']
            self.user = config['user']
        except Exception:
            raise Exception("Missing fields in config! ('ip' and 'user' required)")

    def pre_setup(self):
        print("Power Control LibVirt Plugin pre setup")
        if self.config['connection_type'] == 'ssh':
            self.executor = SshExecutor(
                self.ip,
                self.user,
                self.config.get('port', 22)
            )
        else:
            self.executor = LocalExecutor()

    def post_setup(self):
        pass

    def teardown(self):
        pass

    def power_cycle(self):
        self.executor.run(f"virsh reset {self.config['domain']}")
        TestRun.executor.wait_for_connection_loss()
        timeout = TestRun.config.get('reboot_timeout')
        if timeout:
            TestRun.executor.wait_for_connection(timedelta(seconds=int(timeout)))
        else:
            TestRun.executor.wait_for_connection()


plugin_class = PowerControlPlugin
