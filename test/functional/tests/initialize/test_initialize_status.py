#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import time

import pytest

from api.cas import cas_module, casctl
from api.cas.cas_module import CasModule
from core.test_run import TestRun
from test_utils import os_utils


@pytest.mark.os_dependent
def test_init_status():
    """
        title: CAS management device status
        description: |
          Verify that CAS management device is present in OS only when CAS modules are loaded.
        pass_criteria:
          - CAS management device present in OS when CAS modules are loaded.
          - CAS management device not present in OS when CAS modules are not loaded.
    """
    with TestRun.step("Check if CAS management device is present in OS."):
        time.sleep(5)
        if cas_module.is_cas_management_dev_present():
            TestRun.LOGGER.info("CAS management device is present in OS when CAS module is loaded.")
        else:
            TestRun.fail("CAS management device is not present in OS when CAS module is loaded.")

    with TestRun.step("Remove CAS module."):
        cas_module.unload_all_cas_modules()

    with TestRun.step("Stop CAS service."):
        casctl.stop()

    with TestRun.step("Check if CAS management device is not present in OS."):
        time.sleep(5)
        if not cas_module.is_cas_management_dev_present():
            TestRun.LOGGER.info(
                "CAS management device is not present in OS when CAS module is not loaded.")
        else:
            TestRun.fail("CAS management device is present in OS when CAS module is not loaded.")

    with TestRun.step("Load CAS modules and start CAS service."):
        os_utils.load_kernel_module(CasModule.cache.value)
        os_utils.load_kernel_module(CasModule.disk.value)
        casctl.start()
