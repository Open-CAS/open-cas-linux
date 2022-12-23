#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from core.test_run import TestRun


class Drbdadm:
    # create metadata for resource
    @staticmethod
    def create_metadata(resource_name: str, force: bool):
        cmd = "drbdadm create-md" + (" --force" if force else "") + f" {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    # enable resource
    @staticmethod
    def up(resource_name: str):
        cmd = f"drbdadm up {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    # disable resource
    @staticmethod
    def down_all():
        cmd = f"drbdadm down all"
        return TestRun.executor.run_expect_success(cmd)

    @staticmethod
    def down(resource_name):
        cmd = f"drbdadm down {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    # promote resource to primary
    @staticmethod
    def set_node_primary(resource_name: str, force=False):
        cmd = f"drbdadm primary {resource_name}"
        cmd += " --force" if force else ""
        return TestRun.executor.run_expect_success(cmd)

    # demote resource to secondary
    @staticmethod
    def set_node_secondary(resource_name: str):
        cmd = f"drbdadm secondary {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    # check status for all or for specified resource
    @staticmethod
    def get_status(resource_name: str = ""):
        cmd = f"drbdadm status {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    @staticmethod
    def in_sync(resource_name: str):
        cmd = f"drbdadm status {resource_name} | grep Inconsistent"
        return TestRun.executor.run(cmd).exit_code == 1

    # wait sync
    @staticmethod
    def wait_for_sync(resource_name: str = ""):
        # ssh connection might timeout in case on long sync
        cmd = f"drbdadm wait-sync {resource_name}"
        return TestRun.executor.run_expect_success(cmd)

    @staticmethod
    def dump_config(resource_name: str):
        cmd = f"drbdadm dump {resource_name}"
        return TestRun.executor.run(cmd)
