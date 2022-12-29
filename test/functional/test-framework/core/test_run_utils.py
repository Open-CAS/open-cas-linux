#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import random
import sys
import traceback

import pytest
from IPy import IP

import core.test_run
from connection.local_executor import LocalExecutor
from connection.ssh_executor import SshExecutor
from core.pair_testing import generate_pair_testing_testcases, register_testcases
from core.plugins import PluginManager
from log.base_log import BaseLogResult
from storage_devices.disk import Disk
from test_utils import disk_finder
from test_utils.dut import Dut

TestRun = core.test_run.TestRun


@classmethod
def __configure(cls, config):
    config.addinivalue_line(
        "markers",
        "require_disk(name, type): require disk of specific type, otherwise skip"
    )
    config.addinivalue_line(
        "markers",
        "require_plugin(name, *kwargs): require specific plugins, otherwise skip"
    )
    config.addinivalue_line(
        "markers",
        "remote_only: run test only in case of remote execution, otherwise skip"
    )
    config.addinivalue_line(
        "markers",
        "os_dependent: run test only if its OS dependent, otherwise skip"
    )
    config.addinivalue_line(
        "markers",
        "multidut(number): test requires a number of different platforms to be executed"
    )
    config.addinivalue_line(
        "markers",
        "parametrizex(argname, argvalues): sparse parametrized testing"
    )
    config.addinivalue_line(
        "markers",
        "CI: marks test for continuous integration pipeline"
    )

    cls.random_seed = config.getoption("--random-seed") or random.randrange(sys.maxsize)
    random.seed(cls.random_seed)


TestRun.configure = __configure


@classmethod
def __prepare(cls, item, config):
    if not config:
        raise Exception("You need to specify DUT config!")

    cls.item = item
    cls.config = config

    req_disks = list(map(lambda mark: mark.args, cls.item.iter_markers(name="require_disk")))
    cls.req_disks = dict(req_disks)
    if len(req_disks) != len(cls.req_disks):
        raise Exception("Disk name specified more than once!")


TestRun.prepare = __prepare


@classmethod
def __attach_log(cls, log_path, target_name=None):
    if target_name is None:
        target_name = posixpath.basename(log_path)
    if cls.config.get('extra_logs'):
        cls.config["extra_logs"][target_name] = log_path
    else:
        cls.config["extra_logs"] = {target_name: log_path}


TestRun.attach_log = __attach_log


@classmethod
def __setup_disk(cls, disk_name, disk_type):
    cls.disks[disk_name] = next(filter(
        lambda disk: disk.disk_type in disk_type.types() and disk not in cls.disks.values(),
        cls.dut.disks
    ), None)
    if not cls.disks[disk_name]:
        pytest.skip("Unable to find requested disk!")


TestRun.__setup_disk = __setup_disk


@classmethod
def __setup_disks(cls):
    cls.disks = {}
    items = list(cls.req_disks.items())
    while items:
        resolved, unresolved = [], []
        for disk_name, disk_type in items:
            (resolved, unresolved)[not disk_type.resolved()].append((disk_name, disk_type))
        resolved.sort(
            key=lambda disk: (lambda disk_name, disk_type: disk_type)(*disk)
        )
        for disk_name, disk_type in resolved:
            cls.__setup_disk(disk_name, disk_type)
        items = unresolved
    cls.dut.req_disks = cls.disks


TestRun.__setup_disks = __setup_disks


@classmethod
def __presetup(cls):
    cls.plugin_manager = PluginManager(cls.item, cls.config)
    cls.plugin_manager.hook_pre_setup()

    if cls.config['type'] == 'ssh':
        try:
            IP(cls.config['ip'])
        except ValueError:
            TestRun.block("IP address from config is in invalid format.")

        port = cls.config.get('port', 22)

        if 'user' in cls.config:
            cls.executor = SshExecutor(
                cls.config['ip'],
                cls.config['user'],
                port
            )
        else:
            TestRun.block("There is no user given in config.")
    elif cls.config['type'] == 'local':
        cls.executor = LocalExecutor()
    else:
        TestRun.block("Execution type (local/ssh) is missing in DUT config!")


TestRun.presetup = __presetup


@classmethod
def __setup(cls):
    if list(cls.item.iter_markers(name="remote_only")):
        if not cls.executor.is_remote():
            pytest.skip()

    Disk.plug_all_disks()
    if cls.config.get('allow_disk_autoselect', False):
        cls.config["disks"] = disk_finder.find_disks()

    try:
        cls.dut = Dut(cls.config)
    except Exception as ex:
        raise Exception(f"Failed to setup DUT instance:\n"
                        f"{str(ex)}\n{traceback.format_exc()}")
    cls.__setup_disks()

    TestRun.LOGGER.info(f"Re-seeding random number generator with seed: {cls.random_seed}")
    random.seed(cls.random_seed)

    cls.plugin_manager.hook_post_setup()


TestRun.setup = __setup


@classmethod
def __makereport(cls, item, call, res):
    if cls.LOGGER is None:
        return None

    cls.outcome = res.outcome
    step_info = {
        'result': res.outcome,
        'exception': str(call.excinfo.value) if call.excinfo else None
    }
    setattr(item, "rep_" + res.when, step_info)

    from _pytest.outcomes import Failed
    from core.test_run import Blocked
    if res.when == "call" and res.failed:
        msg = f"{call.excinfo.type.__name__}: {call.excinfo.value}"
        if call.excinfo.type is Failed:
            cls.LOGGER.error(msg)
        elif call.excinfo.type is Blocked:
            cls.LOGGER.blocked(msg)
        else:
            cls.LOGGER.exception(msg)
    elif res.when == "setup" and res.failed:
        msg = f"{call.excinfo.type.__name__}: {call.excinfo.value}"
        cls.LOGGER.exception(msg)
        res.outcome = "failed"

    if res.outcome == "skipped":
        cls.LOGGER.skip("Test skipped.")

    if res.when in ["call", "setup"] and cls.LOGGER.get_result() >= BaseLogResult.FAILED:
        res.outcome = "failed"
        # To print additional message in final test report, assign it to res.longrepr

    cls.LOGGER.generate_summary(item, cls.config.get('meta'))


TestRun.makereport = __makereport


@classmethod
def __generate_tests(cls, metafunc):
    marks = getattr(metafunc.function, "pytestmark", [])

    parametrizex_marks = [
        mark for mark in marks if mark.name == "parametrizex"
    ]

    if not parametrizex_marks:
        random.seed(TestRun.random_seed)
        return

    argnames = []
    argvals = []
    for mark in parametrizex_marks:
        argnames.append(mark.args[0])
        argvals.append(list(mark.args[1]))

    if metafunc.config.getoption("--parametrization-type") == "full":
        for name, values in zip(argnames, argvals):
            metafunc.parametrize(name, values)
    elif metafunc.config.getoption("--parametrization-type") == "pair":
        test_cases = generate_pair_testing_testcases(*argvals)

        register_testcases(metafunc, argnames, test_cases)
    else:
        raise Exception("Not supported parametrization type")

    random.seed(TestRun.random_seed)


TestRun.generate_tests = __generate_tests


@classmethod
def __addoption(cls, parser):
    parser.addoption("--parametrization-type", choices=["pair", "full"], default="pair")
    parser.addoption("--random-seed", type=int, default=None)


TestRun.addoption = __addoption


@classmethod
def __teardown(cls):
    for _ in cls.use_all_duts():
        if cls.plugin_manager:
            cls.plugin_manager.hook_teardown()


TestRun.teardown = __teardown
