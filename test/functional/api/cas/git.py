#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os

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


def get_release_tags():
    repo_path = os.path.join(TestRun.usr.working_dir, ".git")
    output = TestRun.executor.run_expect_success(f"git --git-dir={repo_path} tag").stdout

    # Tags containing '-' or '_' are not CAS release versions
    tags = [v for v in output.splitlines() if "-" not in v and "_" not in v]

    return tags
