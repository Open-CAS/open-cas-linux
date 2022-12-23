#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


from log.base_log import BaseLog, escape
from log.html_iteration_log import HtmlIterationLog
from log.html_log_config import HtmlLogConfig
from log.html_main_log import HtmlMainLog
from log.html_setup_log import HtmlSetupLog


class HtmlLogManager(BaseLog):
    def __init__(self, begin_message=None, log_config=None):
        super().__init__(begin_message)
        self._config = HtmlLogConfig() if log_config is None else log_config
        self._main = None
        self._log_setup = None
        self._log_iterations = []
        self._current_log = None
        self._files_path = None

    def __add(self, msg):
        pass

    def begin(self, message):
        self._files_path = self._config.create_html_test_log(message)
        self._main = HtmlMainLog(message, self._config)
        self._log_setup = HtmlSetupLog(message, config=self._config)
        self._current_log = self._log_setup
        self._main.begin(message)
        self._current_log.begin(message)
        self.__add("begin: " + message)

    @property
    def base_dir(self):
        return self._files_path

    def get_result(self):
        log_result = self._log_setup.get_result()
        for iteration in self._log_iterations:
            if log_result.value < iteration.get_result().value:
                log_result = iteration.get_result()
        return log_result

    def end(self):
        self._log_setup.end()
        self._main.end_setup_iteration(self._log_setup.get_result())
        log_result = self.get_result()
        self._main.end(log_result)
        self.__add("end")

    def add_build_info(self, message):
        self._main.add_build_info(escape(message))

    def start_iteration(self, message):
        message = escape(message)
        self._log_iterations.append(HtmlIterationLog(message, message, self._config))
        self._main.start_iteration(self._config.get_iteration_id())
        self._current_log = self._log_iterations[-1]
        self._current_log.begin(message)
        self._log_setup.start_iteration(message)
        self.__add("start_iteration: " + message)

    def end_iteration(self):
        self._current_log.end()
        self._main.end_iteration(self._current_log.get_result())
        self._log_setup.end_iteration(self._current_log.get_result())
        self._current_log.iteration_closed = True
        self._current_log = self._log_setup
        self.__add("end_iteration: ")
        return self._current_log

    def debug(self, message):
        self._current_log.debug(escape(message))
        self.__add("debug: " + message)

    def info(self, message):
        self._current_log.info(escape(message))
        self.__add("info: " + message)

    def workaround(self, message):
        self._current_log.workaround(escape(message))
        self.__add(": " + message)

    def warning(self, message):
        self._current_log.warning(escape(message))
        self.__add(": " + message)

    def skip(self, message):
        self._current_log.skip(escape(message))
        self.__add("warning: " + message)

    def error(self, message):
        self._current_log.error(escape(message))
        self.__add("error: " + message)

    def blocked(self, message):
        self._current_log.blocked(escape(message))
        self.__add(f'blocked: {message}')
        self.end_all_groups()

    def exception(self, message):
        self._current_log.exception(escape(message))
        self.__add("exception: " + message)
        self.end_all_groups()

    def critical(self, message):
        self._current_log.critical(escape(message))
        self.__add("critical: " + message)
        self.end_all_groups()

    def start_group(self, message):
        self._current_log.start_group(escape(message))
        self.__add("start_group: " + message)

    def end_group(self):
        self._current_log.end_group()
        self.__add("end_group")

    def end_all_groups(self):
        for iteration in reversed(self._log_iterations):
            if not iteration.iteration_closed:
                self.end_iteration()
        self._current_log.end_all_groups()
