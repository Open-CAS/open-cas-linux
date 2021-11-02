#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import logging

from tests import conftest
from core.test_run import TestRun
from api.cas import git
from api.cas import cas_module
from test_utils import os_utils
from test_utils.output import CmdException


def rsync_opencas_sources():
    TestRun.LOGGER.info("Copying Open CAS repository to DUT")
    TestRun.executor.rsync_to(
        f"{TestRun.usr.repo_dir}/",
        f"{TestRun.usr.working_dir}/",
        exclude_list=["test/functional/results/"],
        delete=True)


def _clean_opencas_repo():
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


def install_opencas():
    TestRun.LOGGER.info("Installing Open CAS")
    output = TestRun.executor.run(
        f"cd {TestRun.usr.working_dir} && "
        f"make install")
    if output.exit_code != 0:
        raise CmdException("Error while installing Open CAS", output)

    TestRun.LOGGER.info("Check if casadm is properly installed.")
    output = TestRun.executor.run("casadm -V")
    if output.exit_code != 0:
        raise CmdException("'casadm -V' command returned an error", output)
    else:
        TestRun.LOGGER.info(output.stdout)


def set_up_opencas(version=None):
    _clean_opencas_repo()

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


def reinstall_opencas(version=None):
    if check_if_installed():
        uninstall_opencas()
    set_up_opencas(version)


def check_if_installed():
    TestRun.LOGGER.info("Check if Open-CAS-Linux is installed")
    output = TestRun.executor.run("which casadm")
    modules_loaded = os_utils.is_kernel_module_loaded(cas_module.CasModule.cache.value)

    if output.exit_code == 0 and modules_loaded:
        TestRun.LOGGER.info("CAS is installed")

        return True
    TestRun.LOGGER.info("CAS not installed")
    return False
