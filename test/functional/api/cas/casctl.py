#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from .cli import *
from core.test_run import TestRun


def help(shortcut: bool = False):
    return TestRun.executor.run(ctl_help(shortcut))


def start():
    return TestRun.executor.run(ctl_start())


def stop(flush: bool = False):
    return TestRun.executor.run(ctl_stop(flush))


def init(force: bool = False):
    return TestRun.executor.run(ctl_init(force))
