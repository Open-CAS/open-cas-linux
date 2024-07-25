#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#


import os
import re

from core.test_run import TestRun
from test_tools.fs_utils import check_if_directory_exists, find_all_files
from test_tools.linux_packaging import DebSet, RpmSet


class Packages:
    # This __init__() method will never be triggered since this class
    # returns other class in __new__() before __init__() is evaluated.
    # It is implemented here only to indicate what arguments can be
    # passed into this class and how are they used.
    def __init__(self, packages_dir: str = ""):
        self.packages_dir = packages_dir

    def __new__(cls, *args, **kwargs):
        distro_id_like = TestRun.executor.run_expect_success(
            "grep -i ID_LIKE /etc/os-release"
        ).stdout

        if re.search("rhel|fedora|suse|sles", distro_id_like):
            return _Rpm(*args, **kwargs)
        elif re.search("debian", distro_id_like):
            return _Deb(*args, **kwargs)
        else:
            distro_id_like = distro_id_like.split("=")[1].strip("\"'")
            raise TypeError(f"{distro_id_like} - not recognized OS distribution")


class _Rpm(RpmSet):
    def __init__(self, packages_dir: str = ""):
        self.packages_dir = packages_dir
        self.packages = get_packages_list("rpm", self.packages_dir)

    def create(
        self,
        sources_dir,
        packages_dir: str = "",
        debug: bool = False,
        arch: str = "",
        source: bool = False,
    ):
        TestRun.LOGGER.info(f"Creating Open CAS RPM packages")

        self.packages_dir = (
            packages_dir or self.packages_dir or os.path.join(sources_dir, "packages")
        )

        self.packages = create_packages(
            "rpm",
            sources_dir,
            self.packages_dir,
            debug,
            arch,
            source,
        )


class _Deb(DebSet):
    def __init__(self, packages_dir: str = ""):
        self.packages_dir = packages_dir
        self.packages = get_packages_list("deb", self.packages_dir)

    def create(
        self,
        sources_dir,
        packages_dir: str = "",
        debug: bool = False,
        arch: str = "",
        source: bool = False,
    ):
        TestRun.LOGGER.info(f"Creating Open CAS DEB packages")

        self.packages_dir = (
            packages_dir or self.packages_dir or os.path.join(sources_dir, "packages")
        )

        self.packages = create_packages(
            "deb",
            sources_dir,
            self.packages_dir,
            debug,
            arch,
            source,
        )


def get_packages_list(package_type: str, packages_dir: str):
    if not check_if_directory_exists(packages_dir):
        return []

    return [
        package for package in find_all_files(packages_dir, recursive=False)
        # include only binary packages (ready to be processed by package manager)
        if package.endswith(package_type.lower())
        and not package.endswith("src." + package_type.lower())
    ]


def create_packages(
    package_type: str,
    sources_dir: str,
    packages_dir: str,
    debug: bool = False,
    arch: str = "",
    source: bool = False,
):
    pckgen = os.path.join(sources_dir, "tools", "pckgen.sh")

    opts = f"{package_type.lower()} --output-dir {packages_dir}"
    if debug:
        opts += " --debug"
    if arch:
        opts += f" --arch {arch}"
    if source:
        opts += f" {'srpm' if package_type.lower() == 'rpm' else 'dsc'}"

    packages_before = get_packages_list(package_type, packages_dir)
    TestRun.executor.run_expect_success(f"{pckgen} {opts} {sources_dir}")
    packages_after = get_packages_list(package_type, packages_dir)

    new_packages = [file for file in packages_after if file not in packages_before]
    packages = new_packages or packages_after

    return packages
