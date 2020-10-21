#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from datetime import timedelta

from api.cas.cas_module import CasModule
from core.test_run import TestRun
from api.cas import cas_module, git
from test_tools.rpm import Rpm
from test_utils import os_utils
from test_utils.output import CmdException


class Installer:
    @staticmethod
    def rsync_opencas():
        TestRun.LOGGER.info("Copying OpenCAS repository to DUT")
        Installer._rsync_opencas(TestRun.usr.repo_dir)

    @staticmethod
    def _rsync_opencas(source: str, timeout: timedelta = timedelta(minutes=5)):
        TestRun.executor.rsync_to(
            f"{source}/",
            f"{TestRun.usr.working_dir}/",
            exclude_list=["test/functional/results/"],
            delete=True,
            timeout=timeout
        )

    @staticmethod
    def _clean_opencas_repo():
        TestRun.LOGGER.info("Cleaning Open CAS repo")
        output = TestRun.executor.run(
            f"cd {TestRun.usr.working_dir} && "
            "make distclean")
        if output.exit_code != 0:
            raise CmdException("Cleaning Open CAS repo executed with nonzero status", output)

    @staticmethod
    def build_opencas():
        TestRun.LOGGER.info("Building Open CAS")
        output = TestRun.executor.run(
            f"cd {TestRun.usr.working_dir} && "
            "./configure && "
            "make -j")
        if output.exit_code != 0:
            raise CmdException("Make command executed with nonzero status", output)

    @staticmethod
    def install_opencas():
        TestRun.LOGGER.info("Installing Open CAS")
        output = TestRun.executor.run(
            f"cd {TestRun.usr.working_dir} && "
            f"make install")
        if output.exit_code != 0 or not Installer._is_casadm_installed():
            raise CmdException("Error while installing Open CAS", output)

    @staticmethod
    def set_up_opencas(version=None):
        Installer._clean_opencas_repo()

        if version:
            git.checkout_cas_version(version)

        Installer.build_opencas()

        Installer.install_opencas()

    @staticmethod
    def uninstall_opencas():
        TestRun.LOGGER.info("Uninstalling Open CAS")
        output = TestRun.executor.run(f"cd {TestRun.usr.working_dir} && make uninstall")
        if output.exit_code != 0:
            raise CmdException("There was an error during uninstall process", output)

    @staticmethod
    def reinstall_opencas(version=None):
        if Installer.check_if_installed():
            Installer.uninstall_opencas()
        Installer.set_up_opencas(version)

    @staticmethod
    def check_if_installed():
        TestRun.LOGGER.info("Check if Open-CAS-Linux is installed")
        casadm_loaded = Installer._is_casadm_installed()
        modules_loaded = os_utils.is_kernel_module_loaded(cas_module.CasModule.cache.value)

        if casadm_loaded and modules_loaded:
            TestRun.LOGGER.info("CAS is installed")
            return True

        TestRun.LOGGER.info("CAS not installed")
        return False

    @staticmethod
    def _is_casadm_installed():
        TestRun.LOGGER.info("Check if 'casadm' is properly installed.")
        output = TestRun.executor.run("casadm -V")
        if output.exit_code != 0:
            return False
        else:
            TestRun.LOGGER.info(output.stdout)
            return True


class RpmInstaller(Installer):
    @staticmethod
    def rsync_opencas():
        if TestRun.usr.rpm_dir is not None:
            TestRun.LOGGER.info("Copying OpenCAS RPM package to DUT")
            Installer._rsync_opencas(TestRun.usr.rpm_dir)
        else:
            Installer.rsync_opencas()

    @staticmethod
    def set_up_opencas(version=None):
        if not TestRun.usr.rpm_dir:
            Installer._clean_opencas_repo()

            if version:
                git.checkout_cas_version(version)

        rpm = Rpm("open-cas-linux")

        if TestRun.usr.rpm_dir is not None:
            rpm.packages_dir = TestRun.usr.rpm_dir
        else:
            rpm.make_rpm(TestRun.usr.working_dir)

        rpm.update_packages_to_install()
        rpm.install_packages()
        os_utils.load_kernel_module(CasModule.cache.value)

    @staticmethod
    def uninstall_opencas():
        TestRun.LOGGER.info("Uninstalling OpenCAS")
        if Rpm.is_package_installed("open-cas-linux"):
            Rpm("open-cas-linux").uninstall_packages()
        else:
            Installer.uninstall_opencas()

    @staticmethod
    def reinstall_opencas(version=None):
        if Installer.check_if_installed():
            RpmInstaller.uninstall_opencas()
        RpmInstaller.set_up_opencas(version)
