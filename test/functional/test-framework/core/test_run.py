#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


from contextlib import contextmanager

import pytest

from log.logger import Log


class Blocked(Exception):
    pass


class TestRun:
    dut = None
    executor = None
    LOGGER: Log = None
    plugin_manager = None
    duts = None
    disks = None

    @classmethod
    @contextmanager
    def use_dut(cls, dut):
        cls.dut = dut
        cls.config = cls.dut.config
        cls.executor = cls.dut.executor
        cls.plugin_manager = cls.dut.plugin_manager
        cls.disks = cls.dut.req_disks
        yield cls.executor
        cls.disks = None
        cls.plugin_manager = None
        cls.executor = None
        # setting cls.config to None omitted (causes problems in the teardown stage of execution)
        cls.dut = None

    @classmethod
    def step(cls, message):
        return cls.LOGGER.step(message)

    @classmethod
    def group(cls, message):
        return cls.LOGGER.group(message)

    @classmethod
    def iteration(cls, iterable, group_name=None):
        TestRun.LOGGER.start_group(f"{group_name}" if group_name is not None else "Iteration list")
        items = list(iterable)
        for i, item in enumerate(items, start=1):
            cls.LOGGER.start_iteration(f"Iteration {i}/{len(items)}")
            yield item
            TestRun.LOGGER.end_iteration()
        TestRun.LOGGER.end_group()

    @classmethod
    def fail(cls, message):
        pytest.fail(message)

    @classmethod
    def block(cls, message):
        raise Blocked(message)
