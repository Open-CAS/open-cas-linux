#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import datetime, timedelta
from functools import partial

from core.test_run import TestRun


class Retry:
    """
    The Retry class implements methods designed to retry execution until desired result.
    The func parameter is meant to be a method. If this method needs args/kwargs, they should be
    encapsulated with the method, i.e. using a partial function (an example of this is contained
    within run_command_until_success())
    """
    @classmethod
    def run_command_until_success(
            cls, command: str, retries: int = None, timeout: timedelta = None
    ):
        # encapsulate method and args/kwargs as a partial function
        func = partial(TestRun.executor.run_expect_success, command)
        return cls.run_while_exception(func, retries=retries, timeout=timeout)

    @classmethod
    def run_while_exception(cls, func, retries: int = None, timeout: timedelta = None):
        result = None

        def wrapped_func():
            nonlocal result
            try:
                result = func()
                return True
            except:
                return False

        cls.run_while_false(wrapped_func, retries=retries, timeout=timeout)
        return result

    @classmethod
    def run_while_false(cls, func, retries: int = None, timeout: timedelta = None):
        if retries is None and timeout is None:
            raise AttributeError("At least one stop condition is required for Retry calls!")
        start = datetime.now()
        retry_calls = 0
        result = func()

        while not result:
            result = func()
            retry_calls += 1
            if result \
                or (timeout is not None and datetime.now() - start > timeout) \
                    or (retries is not None and retry_calls == retries):
                break
        return result
