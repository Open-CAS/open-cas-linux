#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import datetime as dt
import os
import json
import pytest

from utils.performance import PerfContainer, ConfigParameter, BuildTypes
from core.test_run import TestRun
from api.cas.casadm_parser import get_casadm_version


@pytest.fixture()
def perf_collector(request):
    container = PerfContainer()
    yield container

    if container.is_empty:
        # No performance metrics submitted by test, no sense in writing any log
        TestRun.LOGGER.warning("No performance metrics collected by test using perf_collector")
        return

    container.insert_config_param(request.node.name.split("[")[0], ConfigParameter.TEST_NAME)
    container.insert_config_param(get_casadm_version(), ConfigParameter.CAS_VERSION)
    container.insert_config_param(TestRun.disks["cache"].disk_type, ConfigParameter.CACHE_TYPE)
    container.insert_config_param(TestRun.disks["core"].disk_type, ConfigParameter.CORE_TYPE)
    container.insert_config_param(dt.now(), ConfigParameter.TIMESTAMP)
    container.insert_config_param(
        request.config.getoption("--build-type"), ConfigParameter.BUILD_TYPE
    )
    if TestRun.dut.ip:
        container.insert_config_param(TestRun.dut.ip, ConfigParameter.DUT)

    perf_log_path = os.path.join(TestRun.LOGGER.base_dir, "perf.json")

    with open(perf_log_path, "w") as dump_file:
        json.dump(container.to_serializable_dict(), dump_file, indent=4)


def pytest_addoption(parser):
    parser.addoption("--build-type", choices=BuildTypes, default="other")


def pytest_configure(config):
    config.addinivalue_line("markers", "performance: performance test")
