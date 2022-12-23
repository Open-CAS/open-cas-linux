#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.html_file_log import HtmlFileLog
from log.group.html_chapter_group_log import HtmlChapterGroupLog
from log.group.html_iteration_group_log import HtmlIterationGroupLog
from datetime import datetime
from lxml.etree import Element


class HtmlFileItemLog(HtmlFileLog):
    def __init__(self, html_file_path, test_title, cfg, iteration_title="Test summary"):
        super().__init__(html_file_path, test_title)
        root = self.get_root()
        self._log_items_store = root.xpath('/html/body')[0]
        self._idx = 0
        self._log_chapters_store = root.xpath('/html/body/section[@id="iteration-chapters"]')[0]
        self._chapter_group = HtmlChapterGroupLog(self._log_chapters_store, cfg, test_title)
        self._main_group = HtmlIterationGroupLog(self._log_items_store, cfg, test_title)
        self._start_time = datetime.now()
        iteration_title_node = root.xpath('/html/body/a/h1')[0]
        iteration_title_node.text = iteration_title
        self._config = cfg
        self._fail_container = root.xpath('/html/body/div/select[@id="error-list-selector"]')[0]

    def __add_error(self, msg_idx, msg, error_class):
        fail_element = Element('option', value=msg_idx)
        fail_element.set('class', error_class)
        fail_element.text = msg
        self._fail_container.append(fail_element)

    def start_iteration(self, message):
        super().begin(message)

    def get_result(self):
        return self._main_group.get_result()

    def begin(self, message):
        self._chapter_group.begin(message)
        self._main_group.begin(message)

    def debug(self, message):
        self._main_group.debug(message)

    def info(self, message):
        self._main_group.info(message)

    def workaround(self, message):
        self._main_group.workaround(message)

    def warning(self, message):
        self._main_group.warning(message)

    def skip(self, message):
        self._main_group.skip(message)

    def error(self, message):
        msg_idx = self._main_group.get_step_id()
        self.__add_error(msg_idx, message, "fail")
        self._main_group.error(message)

    def blocked(self, message):
        msg_idx = self._main_group.get_step_id()
        self.__add_error(msg_idx, message, "blocked")
        self._main_group.blocked(message)

    def exception(self, message):
        msg_idx = self._main_group.get_step_id()
        self.__add_error(msg_idx, message, "exception")
        self._main_group.exception(message)

    def critical(self, message):
        msg_idx = self._main_group.get_step_id()
        self.__add_error(msg_idx, message, "critical")
        self._main_group.critical(message)

    def start_group(self, message):
        self._chapter_group.start_group(message)
        self._main_group.start_group(message)

    def end_group(self):
        ref_group = self._main_group.get_current_group()
        self._chapter_group.set_result(ref_group.get_result())
        self._main_group.end_group()
        self._chapter_group.end_dir_group(ref_group)

    def end_all_groups(self):
        while self._main_group._successor is not None:
            self.end_group()

    def end(self):
        while self._main_group._successor is not None:
            self.end_group()
        self.end_group()
        time_result = datetime.now() - self._start_time
        time_node = self.get_root().xpath('/html/body/div[@class="iteration-execution-time"]')[0]
        status_node = self.get_root().xpath('/html/body/div[@class="iteration-status"]')[0]
        self._config.end_iteration_func(
            time_node, status_node, time_result.total_seconds(), self.get_result())
        super().end()
