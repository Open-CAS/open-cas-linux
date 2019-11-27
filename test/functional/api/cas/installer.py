#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import logging

from tests import conftest
from core.test_run import TestRun


def install_opencas():
    TestRun.LOGGER.info("Copying Open CAS repository to DUT")
    TestRun.executor.rsync(
        f"{TestRun.plugins['opencas'].repo_dir}/",
        f"{TestRun.plugins['opencas'].working_dir}/",
        exclude_list=["test/functional/results/"],
        delete=True)

    TestRun.LOGGER.info("Building Open CAS")
    output = TestRun.executor.run(
        f"cd {TestRun.plugins['opencas'].working_dir} && "
        "./configure && "
        "make -j")
    if output.exit_code != 0:
        TestRun.exception(
            f"Make command executed with nonzero status: {output.stdout}\n{output.stderr}")

    TestRun.LOGGER.info("Installing Open CAS")
    output = TestRun.executor.run(
        f"cd {TestRun.plugins['opencas'].working_dir} && "
        f"make install")
    if output.exit_code != 0:
        TestRun.exception(
            f"Error while installing Open CAS: {output.stdout}\n{output.stderr}")

    TestRun.LOGGER.info("Check if casadm is properly installed.")
    output = TestRun.executor.run("casadm -V")
    if output.exit_code != 0:
        TestRun.exception(
            f"'casadm -V' command returned an error: {output.stdout}\n{output.stderr}")
    else:
        TestRun.LOGGER.info(output.stdout)


def uninstall_opencas():
    TestRun.LOGGER.info("Uninstalling Open CAS")
    output = TestRun.executor.run("casadm -V")
    if output.exit_code != 0:
        TestRun.exception("Open CAS is not properly installed")
    else:
        TestRun.executor.run(
            f"cd {TestRun.plugins['opencas'].working_dir} && "
            f"make uninstall")
        if output.exit_code != 0:
            TestRun.exception(
                f"There was an error during uninstall process: {output.stdout}\n{output.stderr}")


def reinstall_opencas():
    if check_if_installed():
        uninstall_opencas()
    install_opencas()


def check_if_installed():
    TestRun.LOGGER.info("Check if Open-CAS-Linux is installed")
    output = TestRun.executor.run("which casadm")
    if output.exit_code == 0:
        TestRun.LOGGER.info("CAS is installed")

        return True
    TestRun.LOGGER.info("CAS not installed")
    return False
