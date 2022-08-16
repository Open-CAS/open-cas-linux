#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os

from core.test_run import TestRun
from connection.local_executor import LocalExecutor
from test_utils.output import CmdException


def get_current_commit_hash(from_dut: bool = False):
    executor = TestRun.executor if from_dut else LocalExecutor()
    repo_path = TestRun.usr.working_dir if from_dut else TestRun.usr.repo_dir

    return executor.run(
        f"cd {repo_path} &&"
        f'git show HEAD -s --pretty=format:"%H"').stdout


def get_current_commit_message():
    local_executor = LocalExecutor()
    return local_executor.run(
        f"cd {TestRun.usr.repo_dir} &&"
        f'git show HEAD -s --pretty=format:"%B"').stdout


def get_commit_hash(cas_version, from_dut: bool = False):
    executor = TestRun.executor if from_dut else LocalExecutor()
    repo_path = TestRun.usr.working_dir if from_dut else TestRun.usr.repo_dir

    output = executor.run(
        f"cd {repo_path} && "
        f"git rev-parse {cas_version}")
    if output.exit_code != 0:
        raise CmdException(f"Failed to resolve '{cas_version}' to commit hash", output)

    TestRun.LOGGER.info(f"Resolved '{cas_version}' as commit {output.stdout}")

    return output.stdout


def get_release_tags():
    repo_path = os.path.join(TestRun.usr.working_dir, ".git")
    output = TestRun.executor.run_expect_success(f"git --git-dir={repo_path} tag").stdout

    # Tags containing '-' or '_' are not CAS release versions
    tags = [v for v in output.splitlines() if "-" not in v and "_" not in v]

    return tags


def checkout_cas_version(cas_version):
    commit_hash = get_commit_hash(cas_version)
    TestRun.LOGGER.info(f"Checkout CAS to {commit_hash}")

    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        f"git checkout --force {commit_hash}")
    if output.exit_code != 0:
        raise CmdException(f"Failed to checkout to {commit_hash}", output)

    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        f"git submodule update --force")
    if output.exit_code != 0:
        raise CmdException(f"Failed to update submodules", output)
