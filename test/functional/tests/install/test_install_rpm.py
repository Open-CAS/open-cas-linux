#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas.cas_module import CasModule
from core.test_run import TestRun
from test_tools.rpm import Rpm
from test_utils import os_utils
from api.cas.installer import RpmInstaller


@pytest.mark.remote_only()
@pytest.mark.uninstall_cas()
def test_install_from_rpm():
    """
        title: Test for installing OpenCAS from RPM
        description: |
          Check if OpenCAS could be installed from RPM and then uninstalled.
        pass_criteria:
          - OpenCAS installs successfully
          - OpenCAS uninstalls successfully
    """
    with TestRun.step("Download and install OpenCAS from RPM."):
        RpmInstaller.rsync_opencas()
        RpmInstaller.set_up_opencas()

    with TestRun.step("Load OpenCAS modules."):
        output = os_utils.load_kernel_module(CasModule.cache.value)
        if output.exit_code != 0:
            TestRun.fail(f"Loading {CasModule.cache.value} module failed.")

    with TestRun.step("Check if OpenCAS is installed correctly from RPM."):
        if not RpmInstaller.check_if_installed():
            TestRun.fail("OpenCAS is not installed correctly.")

    with TestRun.step("Uninstall OpenCAS from RPM."):
        RpmInstaller.uninstall_opencas()

    with TestRun.step("Check if OpenCAS is uninstalled correctly."):
        if RpmInstaller.check_if_installed():
            TestRun.fail("OpenCAS should be uninstalled.")
        if Rpm.is_package_installed("open-cas-linux"):
            TestRun.fail("OpenCAS should be uninstalled from RPM.")
