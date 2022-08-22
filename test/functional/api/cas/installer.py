#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import logging
import os

from tests import conftest
from core.test_run import TestRun
from api.cas import cas_module, git
from api.cas.version import get_installed_cas_version
from test_utils import os_utils
from test_utils.output import CmdException


def rsync_opencas_sources():
    TestRun.LOGGER.info("Copying Open CAS repository to DUT")
    TestRun.executor.rsync_to(
        # Place an empty string as the last argument to os.path.join()
        # to make sure path ends with directory separator.
        # Needed for rsync to copy only contents of a directory
        # and not the directory itself.
        os.path.join(TestRun.usr.repo_dir, ''),
        os.path.join(TestRun.usr.working_dir, ''),
        exclude_list=["test/functional/results/"],
        delete=True)


def clean_opencas_repo():
    TestRun.LOGGER.info("Cleaning Open CAS repo")
    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        "make distclean")
    if output.exit_code != 0:
        raise CmdException("make distclean command executed with nonzero status", output)


def build_opencas():
    TestRun.LOGGER.info("Building Open CAS")
    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        "./configure && "
        "make -j")
    if output.exit_code != 0:
        raise CmdException("Make command executed with nonzero status", output)


def install_opencas(destdir: str = ""):
    TestRun.LOGGER.info("Installing Open CAS")

    if destdir:
        destdir = os.path.join(TestRun.usr.working_dir, destdir)

    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        f"make {'DESTDIR='+destdir if destdir else ''} install")
    if output.exit_code != 0:
        raise CmdException("Failed to install Open CAS", output)

    output = TestRun.executor.run("rmmod cas_cache cas_disk; modprobe cas_cache")
    if output.exit_code != 0:
        raise CmdException("Failed to reload modules", output)

    if destdir:
        return

    TestRun.LOGGER.info("Check if casadm is properly installed.")
    output = TestRun.executor.run("casadm -V")
    if output.exit_code != 0:
        raise CmdException("'casadm -V' command returned an error", output)

    TestRun.LOGGER.info(output.stdout)


def set_up_opencas(version: str = ""):
    clean_opencas_repo()

    if version:
        git.checkout_cas_version(version)

    build_opencas()
    install_opencas()


def uninstall_opencas():
    TestRun.LOGGER.info("Uninstalling Open CAS")
    output = TestRun.executor.run("casadm -V")
    if output.exit_code != 0:
        raise CmdException("Open CAS is not properly installed", output)
    else:
        TestRun.executor.run(
            f"cd {TestRun.usr.working_dir} && "
            f"make uninstall")
        if output.exit_code != 0:
            raise CmdException("There was an error during uninstall process", output)


def reinstall_opencas(version: str = ""):
    if check_if_installed():
        uninstall_opencas()
    set_up_opencas(version)


def check_if_installed(version: str = ""):
    TestRun.LOGGER.info("Check if Open CAS Linux is installed")
    output = TestRun.executor.run("which casadm")
    modules_loaded = os_utils.is_kernel_module_loaded(cas_module.CasModule.cache.value)

    if output.exit_code != 0 or not modules_loaded:
        TestRun.LOGGER.info("CAS is not installed")
        return False

    TestRun.LOGGER.info("CAS is installed")

    if version:
        TestRun.LOGGER.info(f"Check for requested CAS version: {version}")
        cas_commit_expected = git.get_commit_hash(version)
        cas_commit_installed = get_installed_cas_version()

        if cas_commit_expected != cas_commit_installed:
            TestRun.LOGGER.info(
                f"CAS version '{version}' is not installed. "
                f"Installed version found: {cas_commit_installed}"
            )
            return False

        TestRun.LOGGER.info(f"CAS version '{version}' is installed")

    return True
