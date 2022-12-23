#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
from datetime import timedelta

from core.test_run import TestRun
from test_utils.output import CmdException


class BaseExecutor:
    def _execute(self, command, timeout):
        raise NotImplementedError()

    def _rsync(self, src, dst, delete, symlinks, checksum, exclude_list, timeout,
               dut_to_controller):
        raise NotImplementedError()

    def rsync_to(self, src, dst, delete=False, symlinks=False, checksum=False, exclude_list=[],
                 timeout: timedelta = timedelta(seconds=90)):
        return self._rsync(src, dst, delete, symlinks, checksum, exclude_list, timeout, False)

    def rsync_from(self, src, dst, delete=False, symlinks=False, checksum=False, exclude_list=[],
                   timeout: timedelta = timedelta(seconds=90)):
        return self._rsync(src, dst, delete, symlinks, checksum, exclude_list, timeout, True)

    def is_remote(self):
        return False

    def is_active(self):
        return True

    def wait_for_connection(self, timeout: timedelta = None):
        pass

    def run(self, command, timeout: timedelta = timedelta(minutes=30)):
        if TestRun.dut and TestRun.dut.env:
            command = f"{TestRun.dut.env} && {command}"
        command_id = TestRun.LOGGER.get_new_command_id()
        ip_info = TestRun.dut.ip if len(TestRun.duts) > 1 else ""
        TestRun.LOGGER.write_command_to_command_log(command, command_id, info=ip_info)
        output = self._execute(command, timeout)
        TestRun.LOGGER.write_output_to_command_log(output, command_id)
        return output

    def run_in_background(self,
                          command,
                          stdout_redirect_path="/dev/null",
                          stderr_redirect_path="/dev/null"):
        command += f" > {stdout_redirect_path} 2> {stderr_redirect_path} &echo $!"
        output = self.run(command)

        if output is not None:
            return int(output.stdout)

    def wait_cmd_finish(self, pid: int, timeout: timedelta = timedelta(minutes=30)):
        self.run(f"tail --pid={pid} -f /dev/null", timeout)

    def check_if_process_exists(self, pid: int):
        output = self.run(f"ps aux | awk '{{print $2 }}' | grep ^{pid}$", timedelta(seconds=10))
        return True if output.exit_code == 0 else False

    def kill_process(self, pid: int):
        # TERM signal should be used in preference to the KILL signal, since a
        # process may install a handler for the TERM signal in order to perform
        # clean-up steps before terminating in an orderly fashion.
        self.run(f"kill -s SIGTERM {pid} &> /dev/null")
        time.sleep(3)
        self.run(f"kill -s SIGKILL {pid} &> /dev/null")

    def run_expect_success(self, command, timeout: timedelta = timedelta(minutes=30)):
        output = self.run(command, timeout)
        if output.exit_code != 0:
            raise CmdException(f"Exception occurred while trying to execute '{command}' command.",
                               output)
        return output

    def run_expect_fail(self, command, timeout: timedelta = timedelta(minutes=30)):
        output = self.run(command, timeout)
        if output.exit_code == 0:
            raise CmdException(f"Command '{command}' executed properly but error was expected.",
                               output)
        return output
