#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os

from core.test_run import TestRun
from connection.local_executor import LocalExecutor
from test_utils.output import CmdException


def get_submodules_paths(from_dut: bool = False):
    executor = TestRun.executor if from_dut else LocalExecutor()
    repo_path = TestRun.usr.working_dir if from_dut else TestRun.usr.repo_dir
    git_params = "config --file .gitmodules --get-regexp path | cut -d' ' -f2"

    output = executor.run(f"git -C {repo_path} {git_params}")
    if output.exit_code != 0:
        raise CmdException("Failed to get submodules paths", output)

    return output.stdout.splitlines()


def get_repo_files(
    branch: str = "HEAD",
    with_submodules: bool = True,
    with_dirs: bool = False,
    from_dut: bool = False,
):
    executor = TestRun.executor if from_dut else LocalExecutor()
    repo_path = TestRun.usr.working_dir if from_dut else TestRun.usr.repo_dir
    git_params = f"ls-tree -r --name-only --full-tree {branch}"

    output = executor.run(f"git -C {repo_path} {git_params}")
    if output.exit_code != 0:
        raise CmdException("Failed to get repo files list", output)

    files = output.stdout.splitlines()

    if with_submodules:
        for subm_path in get_submodules_paths(from_dut):
            output = executor.run(f"git -C {os.path.join(repo_path, subm_path)} {git_params}")
            if output.exit_code != 0:
                raise CmdException(f"Failed to get {subm_path} submodule repo files list", output)

            subm_files = [os.path.join(subm_path, file) for file in output.stdout.splitlines()]
            files.extend(subm_files)

    if with_dirs:
        # use set() to get unique values only
        dirs = set(os.path.dirname(file) for file in files)
        files.extend(dirs)

    # change to absolute paths and remove empty values
    files = [os.path.realpath(os.path.join(repo_path, file)) for file in files if file]

    return files


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
