#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import datetime
from log.base_log import BaseLog, BaseLogResult


class HtmlGroupLog(BaseLog):
    def __init__(self, constructor, html_base_element, cfg, begin_message, id_):
        super().__init__(begin_message)
        self._successor = None
        self.__factory = constructor
        self.__log_main_store = html_base_element
        self._id = id_
        self._container = None
        self._header = None
        self.__msg_idx = 0
        self._start_time = datetime.now()
        self._cfg = cfg
        self._header_msg_type = type(begin_message)

    def begin(self, message):
        policy = self._cfg.get_policy(type(message))
        self._header, self._container = policy.group_begin(self._id, message, self.__log_main_store)
        super().begin(message)

    def get_step_id(self):
        if self._successor is not None:
            return self._successor.get_step_id()
        else:
            return f'step.{self._id}.{self.__msg_idx}'

    def __add_test_step(self, message, result=BaseLogResult.PASSED):
        policy = self._cfg.get_policy(type(message))
        policy.standard(self.get_step_id(), message, result, self._container)
        self.__msg_idx += 1

    def get_main_log_store(self):
        return self.__log_main_store

    def start_group(self, message):
        self._header_msg_type = type(message)
        if self._successor is not None:
            result = self._successor.start_group(message)
        else:
            new_id = f"{self._id}.{self.__msg_idx}"
            self.__msg_idx += 1
            self._successor = self.__factory(self._container, self._cfg, message, new_id)
            self._successor.begin(message)
            result = self._successor
        return result

    def end_group(self):
        if self._successor is not None:
            if self._successor._successor is None:
                self._successor.end()
                result = self._successor
                self._successor = None
            else:
                result = self._successor.end_group()
        else:
            self.end()
            result = self
        return result

    def debug(self, message):
        if self._successor is not None:
            self._successor.debug(message)
        else:
            self.__add_test_step(message, BaseLogResult.DEBUG)
        return super().debug(message)

    def info(self, message):
        if self._successor is not None:
            self._successor.info(message)
        else:
            self.__add_test_step(message)
        super().info(message)

    def workaround(self, message):
        if self._successor is not None:
            self._successor.workaround(message)
        else:
            self.__add_test_step(message, BaseLogResult.WORKAROUND)
        super().workaround(message)

    def warning(self, message):
        if self._successor is not None:
            self._successor.warning(message)
        else:
            self.__add_test_step(message, BaseLogResult.WARNING)
        super().warning(message)

    def skip(self, message):
        if self._successor is not None:
            self._successor.skip(message)
        else:
            self.__add_test_step(message, BaseLogResult.SKIPPED)
        super().skip(message)

    def error(self, message):
        if self._successor is not None:
            self._successor.error(message)
        else:
            self.__add_test_step(message, BaseLogResult.FAILED)
        super().error(message)

    def blocked(self, message):
        if self._successor is not None:
            self._successor.blocked(message)
        else:
            self.__add_test_step(message, BaseLogResult.BLOCKED)
        super().blocked(message)

    def critical(self, message):
        if self._successor is not None:
            self._successor.critical(message)
        else:
            self.__add_test_step(message, BaseLogResult.CRITICAL)
        super().critical(message)

    def exception(self, message):
        if self._successor is not None:
            self._successor.exception(message)
        else:
            self.__add_test_step(message, BaseLogResult.EXCEPTION)
        super().exception(message)

    def end(self):
        return super().end()

    def get_current_group(self):
        if self._successor is not None:
            result = self._successor.get_current_group()
        else:
            result = self
        return result
