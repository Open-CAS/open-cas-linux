#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from enum import Enum
from re import sub


class BaseLogResult(Enum):
    DEBUG = 10
    PASSED = 11
    WORKAROUND = 12
    WARNING = 13
    SKIPPED = 14
    FAILED = 15
    EXCEPTION = 16
    BLOCKED = 17
    CRITICAL = 18


def escape(msg):
    return sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', msg)


class BaseLog():
    def __init__(self, begin_message=None):
        self.__begin_msg = begin_message
        self.__result = BaseLogResult.PASSED

    def __enter__(self):
        if self.__begin_msg is not None:
            self.begin(self.__begin_msg)
        else:
            self.begin("Start BaseLog ...")

    def __exit__(self, *args):
        self.end()

    def __try_to_set_new_result(self, new_result):
        if new_result.value > self.__result.value:
            self.__result = new_result

    def begin(self, message):
        pass

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def workaround(self, message):
        self.__try_to_set_new_result(BaseLogResult.WORKAROUND)

    def warning(self, message):
        self.__try_to_set_new_result(BaseLogResult.WARNING)

    def skip(self, message):
        self.__try_to_set_new_result(BaseLogResult.SKIPPED)

    def error(self, message):
        self.__try_to_set_new_result(BaseLogResult.FAILED)

    def blocked(self, message):
        self.__try_to_set_new_result(BaseLogResult.BLOCKED)

    def exception(self, message):
        self.__try_to_set_new_result(BaseLogResult.EXCEPTION)

    def critical(self, message):
        self.__try_to_set_new_result(BaseLogResult.CRITICAL)

    def end(self):
        return self.__result

    def get_result(self):
        return self.__result
