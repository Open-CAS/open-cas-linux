#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import os
import re

from core.test_run import TestRun
from test_utils.output import CmdException


class RpmSet():
    def __init__(self, packages_paths: list):
            self.packages = packages_paths

    def _get_package_names(self):
        return " ".join([os.path.splitext(os.path.basename(pckg))[0] for pckg in self.packages])

    def check_if_installed(self):
        if not self.packages:
            raise ValueError("No packages given.")

        output = TestRun.executor.run(f"rpm --query {self._get_package_names()}")

        return output.exit_code == 0

    def install(self):
        TestRun.LOGGER.info(f"Installing RPM packages")

        if not self.packages:
            raise ValueError("No packages given.")

        output = TestRun.executor.run(
            f"rpm --upgrade --verbose --replacepkgs {' '.join(self.packages)}"
        )
        if (
            output.exit_code != 0
            or re.search("error", output.stdout, re.IGNORECASE)
            or re.search("error", output.stderr, re.IGNORECASE)
        ):
            raise CmdException("Installation failed or errors found during the process.", output)

    def uninstall(self):
        TestRun.LOGGER.info(f"Uninstalling RPM packages")

        if not self.check_if_installed():
            raise FileNotFoundError("Could not uninstall - packages not installed yet.")

        output = TestRun.executor.run(f"rpm --erase --verbose {self._get_package_names()}")
        if (
            output.exit_code != 0
            or re.search("error", output.stdout, re.IGNORECASE)
            or re.search("error", output.stderr, re.IGNORECASE)
        ):
            raise CmdException("Uninstallation failed or errors found during the process.", output)

    @staticmethod
    def uninstall_all_matching(*packages_names: str):
        for name in packages_names:
            TestRun.LOGGER.info(f"Uninstalling all RPM packages matching '{name}'")
            TestRun.executor.run_expect_success(
                f"rpm --query --all | grep {name} | "
                f"xargs --no-run-if-empty rpm --erase --verbose"
            )


class DebSet():
    def __init__(self, packages_paths: list):
            self.packages = packages_paths

    def _get_package_names(self):
        return " ".join([os.path.basename(pckg).split("_")[0] for pckg in self.packages])

    def check_if_installed(self):
        if not self.packages:
            raise ValueError("No packages given.")

        output = TestRun.executor.run(f"dpkg --no-pager --list {self._get_package_names()}")

        return output.exit_code == 0

    def install(self):
        TestRun.LOGGER.info(f"Installing DEB packages")

        if not self.packages:
            raise ValueError("No packages given.")

        output = TestRun.executor.run(
            f"dpkg --force-confdef --force-confold --install {' '.join(self.packages)}"
        )
        if (
            output.exit_code != 0
            or re.search("error", output.stdout, re.IGNORECASE)
            or re.search("error", output.stderr, re.IGNORECASE)
        ):
            raise CmdException("Installation failed or errors found during the process.", output)

    def uninstall(self):
        TestRun.LOGGER.info(f"Uninstalling DEB packages")

        if not self.check_if_installed():
            raise FileNotFoundError("Could not uninstall - packages not installed yet.")

        output = TestRun.executor.run(f"dpkg --purge {self._get_package_names()}")
        if (
            output.exit_code != 0
            or re.search("error", output.stdout, re.IGNORECASE)
            or re.search("error", output.stderr, re.IGNORECASE)
        ):
            raise CmdException("Uninstallation failed or errors found during the process.", output)

    @staticmethod
    def uninstall_all_matching(*packages_names: str):
        for name in packages_names:
            TestRun.LOGGER.info(f"Uninstalling all DEB packages matching '{name}'")
            TestRun.executor.run_expect_success(
                f"dpkg-query --no-pager --showformat='${{Package}}\n' --show | grep {name} | "
                f"xargs --no-run-if-empty dpkg --purge"
            )
