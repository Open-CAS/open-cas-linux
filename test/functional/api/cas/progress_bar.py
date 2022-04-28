#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re
from datetime import timedelta

import paramiko

from core.test_run import TestRun
from test_utils.os_utils import wait


def check_progress_bar(command: str, progress_bar_expected: bool = True):
    TestRun.LOGGER.info(f"Check progress for command: {command}")
    try:
        stdin, stdout, stderr = TestRun.executor.ssh.exec_command(command, get_pty=True)
    except paramiko.SSHException as e:
        raise ConnectionError(f"An exception occurred while executing command: {command}\n{e}")

    if not wait(lambda: stdout.channel.recv_ready(), timedelta(seconds=10), timedelta(seconds=1)):
        if not progress_bar_expected:
            TestRun.LOGGER.info("Progress bar did not appear when output was redirected to a file.")
            return
        else:
            TestRun.fail("Progress bar did not appear in 10 seconds.")
    else:
        if not progress_bar_expected:
            TestRun.fail("Progress bar appear when output was redirected to a file.")

    percentage = 0
    while True:
        output = stdout.channel.recv(1024).decode('utf-8')
        search = re.search(r'\d+.\d+', output)
        last_percentage = percentage
        if search:
            TestRun.LOGGER.info(output)
            percentage = float(search.group())
            if last_percentage > percentage:
                TestRun.fail(f"Progress decrease from {last_percentage}% to {percentage}%.")
            elif percentage < 0:
                TestRun.fail(f"Progress must be greater than 0%. Actual: {percentage}%.")
            elif percentage > 100:
                TestRun.fail(f"Progress cannot be greater than 100%. Actual: {percentage}%.")
        elif (stdout.channel.exit_status_ready() or not output) and last_percentage > 0:
            TestRun.LOGGER.info("Progress complete.")
            break
        elif stdout.channel.exit_status_ready() and last_percentage == 0:
            TestRun.fail("Process has exited but progress doesn't complete.")
