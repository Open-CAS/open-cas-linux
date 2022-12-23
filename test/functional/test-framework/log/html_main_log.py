#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.html_file_log import HtmlFileLog
from lxml.etree import Element


class HtmlMainLog(HtmlFileLog):
    def __init__(self, title, config):
        super().__init__(config.get_main_file_path(), title)
        self._config = config
        self.__current_iteration_id = None
        root = self.get_root()
        test_title_div = root.xpath('/html/body/div/div/div/div[@class="sidebar-test-title"]')[0]
        test_title_div.text = title
        self.__build_information_set = root.xpath(
            '/html/body/div/div/div/div[@id="sidebar-tested-build"]')[0]

    def add_build_info(self, message):
        build_info = Element("div")
        build_info.text = message
        self.__build_information_set.append(build_info)

    def start_iteration(self, iteration_id):
        self.__current_iteration_id = iteration_id

    def end_iteration(self):
        pass

    def end_iteration(self, iteration_result):
        root = self.get_root()
        iteration_selector_div = root.xpath('/html/body/div/div/div[@id="iteration-selector"]')
        iteration_selector_select = root.xpath(
            '/html/body/div/div/select[@id="sidebar-iteration-list"]')[0]
        self._config.end_iteration(iteration_selector_div,
                                   iteration_selector_select,
                                   self.__current_iteration_id,
                                   iteration_result)

    def end_setup_iteration(self, result):
        root = self.get_root()
        iteration_selector_div = root.xpath('/html/body/div/div/div[@id="iteration-selector"]')[0]
        iteration_selector_select = root.xpath(
            '/html/body/div/div/select[@id="sidebar-iteration-list"]')[0]
        self._config.end_setup_iteration(iteration_selector_div, iteration_selector_select, result)

    def end(self, result):
        root = self.get_root()
        test_status_div = root.xpath('/html/body/div/div/div/div[@class="sidebar-test-status"]')
        self._config.end_main_log(test_status_div, result)
        super().end()
