#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import re

from core.test_run import TestRun
from test_tools.fs_utils import Permissions, PermissionsUsers, PermissionSign
from test_utils.filesystem.fs_item import FsItem


def test_checksec():
    """
        title: Checking defenses enabled compilation flags.
        description: |
          Check if Open CAS executable file was compiled with defenses enabled compilation flags.
        pass_criteria:
          - For casadm script returns:
            RELRO       STACK CANARY  NX          PIE          RPATH     RUNPATH     FILE
            Full RELRO  Canary found  NX enabled  PIE enabled  No RPATH  No RUNPATH  /sbin/casadm.
    """
    with TestRun.step("Prepare checksec script"):
        checksec_path = os.path.join(
            TestRun.usr.working_dir,
            "test/functional/test-framework/test_tools/checksec.sh"
        )
        checksec = FsItem(checksec_path)
        checksec.chmod(Permissions.x, PermissionsUsers.u, PermissionSign.add)

    with TestRun.step("Check casadm compilation flags"):
        casadm_binary = "/sbin/casadm"
        header_expected = ["RELRO", "STACK CANARY", "NX", "PIE", "RPATH", "RUNPATH", "FILE"]
        binary_expected = ["Full RELRO", "Canary found", "NX enabled", "PIE enabled", "No RPATH",
                           "No RUNPATH", casadm_binary]
        result_lines = TestRun.executor.run_expect_success(
            f'{checksec_path} --file {casadm_binary}').stdout.splitlines()
        header_found = False
        for line in result_lines:
            if not header_found:
                if line.startswith("RELRO"):
                    header_found = True
                    header = line
                continue
            # remove formatting from output
            result = re.sub(r'\x1B\[[0-9;]*m', '', line)
            break
        header = [i.strip() for i in header.split("  ") if i != '']
        if header != header_expected:
            TestRun.LOGGER.error(
                'Incorrect header detected!\n'
                f'Expected: {"  ".join(header_expected)},\n'
                f'Actual:   {"  ".join(header)}')
        result = [i.strip() for i in result.split("  ") if i != '']
        if result != binary_expected:
            TestRun.LOGGER.error(
                'Incorrect compilation flags!\n'
                f'Expected: {"  ".join(binary_expected)},\n'
                f'Actual:   {"  ".join(result)}')
