#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import os
import re

from api.cas.installer import clean_opencas_repo, rsync_opencas_sources
from core.test_run import TestRun
from test_tools.fs_utils import (
    check_if_regular_file_exists,
    check_if_symlink_exists,
    readlink,
    remove,
)
from test_tools.packaging import Packages


modules_links_dir = "/lib/modules/$(uname -r)/weak-updates/block/opencas"
modules_names = ["cas_cache.ko"]


def test_weak_modules():
    """
    title: Test for weak-modules symlinks handling.
    description: |
      Test if symlinks for CAS modules in kernels's weak-updates directory
      are properly created and removed during RPM package install/uninstall.
    pass_criteria:
      - working symlinks for CAS modules are created after installation
      - no broken symlinks are left after uninstallation
    """

    with TestRun.step("Check for supported RPM based OS distribution"):
        distro_id_like = TestRun.executor.run_expect_success(
            "grep -i ID_LIKE /etc/os-release"
        ).stdout

        if not re.search("rhel|fedora", distro_id_like):
            distro_id_like = distro_id_like.split("=")[1].strip("\"'")
            TestRun.LOGGER.error(
                f"OS type - {distro_id_like}: this distribution "
                f"does not support weak-modules mechanism"
            )
            return

    with TestRun.step("Create RPM packages"):
        rsync_opencas_sources()
        clean_opencas_repo()

        cas_pkg = Packages()
        cas_pkg.create(TestRun.usr.working_dir)

    with TestRun.step("Remove any previous installations and cleanup"):
        cas_pkg.uninstall("open-cas-linux")
        remove(modules_links_dir, recursive=True, force=True)

    with TestRun.step("Install RPM packages and check for module symlinks"):
        cas_pkg.install()

        missing_links = []
        for module in modules_names:
            module_link = os.path.join(modules_links_dir, module)
            if not check_if_symlink_exists(module_link):
                resolved_path = TestRun.executor.run_expect_success(f"echo {module_link}").stdout
                missing_links.append(resolved_path)

        if missing_links:
            TestRun.fail(
                f"No CAS modules links found in weak-updates directory "
                f"after installation:\n{', '.join(missing_links)}"
            )

        broken_links = []
        for module in modules_names:
            module_link = os.path.join(modules_links_dir, module)
            module_file = readlink(module_link)
            if not check_if_regular_file_exists(module_file):
                resolved_path = TestRun.executor.run_expect_success(f"echo {module_link}").stdout
                broken_links.append(resolved_path)

        if broken_links:
            TestRun.fail(
                f"Broken CAS modules links found in weak-updates directory "
                f"after installation:\n{', '.join(broken_links)}"
            )

    with TestRun.step("Uninstall RPM packages and check if symlinks were removed"):
        cas_pkg.uninstall()

        existing_links = []
        for module in modules_names:
            module_link = os.path.join(modules_links_dir, module)
            if check_if_symlink_exists(module_link):
                resolved_path = TestRun.executor.run_expect_success(f"echo {module_link}").stdout
                existing_links.append(resolved_path)

        if existing_links:
            TestRun.fail(
                f"CAS modules links found in weak-updates directory "
                f"after uninstallation:\n{', '.join(existing_links)}"
            )
