#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from core.test_run import TestRun
from connection.local_executor import LocalExecutor


def get_current_commit_hash():
    local_executor = LocalExecutor()
    return local_executor.run(
        f"cd {TestRun.usr.repo_dir} &&"
        f'git show HEAD -s --pretty=format:"%H"').stdout


def get_current_commit_message():
    local_executor = LocalExecutor()
    return local_executor.run(
        f"cd {TestRun.usr.repo_dir} &&"
        f'git show HEAD -s --pretty=format:"%B"').stdout
