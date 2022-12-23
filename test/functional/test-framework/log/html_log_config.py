#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
from os import path, environ, makedirs
from datetime import datetime
from shutil import copyfile
from lxml.etree import Element
from log.base_log import BaseLogResult
from log.presentation_policy import null_policy


def convert_seconds_to_str(time_in_sec):
    h = str(int(time_in_sec / 3600) % 24).zfill(2)
    m = str(int(time_in_sec / 60) % 60).zfill(2)
    s = str(int(time_in_sec % 60)).zfill(2)
    time_msg = f"{h}:{m}:{s} [s]"
    if time_in_sec > 86400:
        time_msg = f"{int(time_in_sec // (3600 * 24))}d {time_msg}"
    return time_msg


class HtmlLogConfig:
    STYLE = {
        BaseLogResult.DEBUG: 'debug',
        BaseLogResult.PASSED: '',
        BaseLogResult.WORKAROUND: 'workaround',
        BaseLogResult.WARNING: 'warning',
        BaseLogResult.SKIPPED: 'skip',
        BaseLogResult.FAILED: 'fail',
        BaseLogResult.BLOCKED: 'blocked',
        BaseLogResult.CRITICAL: 'critical',
        BaseLogResult.EXCEPTION: 'exception'}

    __MAIN = 'main'
    __SETUP = 'setup'
    __T_ITERATION = 'iteration'
    __FRAMEWORK_T_FOLDER = 'template'

    MAIN = __MAIN + '.html'
    CSS = __MAIN + '.css'
    JS = __MAIN + '.js'

    ITERATION_FOLDER = 'iterations'
    SETUP = __SETUP + ".html"

    def iteration(self):
        return f'{HtmlLogConfig.__T_ITERATION}_{str(self._iteration_id).zfill(3)}.html'

    def __init__(self, base_dir=None, presentation_policy=null_policy):
        self._log_base_dir = base_dir
        if base_dir is None:
            if os.name == 'nt':
                self._log_base_dir = 'c:\\History'
            else:
                if environ["USER"] == 'root':
                    self._log_base_dir = '/root/history'
                else:
                    self._log_base_dir = f'/home/{environ["USER"]}'
        self._log_dir = None
        self._presentation_policy = {}
        self.register_presentation_policy(str, presentation_policy)
        self._iteration_id = 0

    def get_iteration_id(self):
        return self._iteration_id

    def get_policy(self, type):
        return self._presentation_policy[type]

    def get_policy_collection(self):
        for type, policy in self._presentation_policy.items():
            yield policy

    def register_presentation_policy(self, type, presentation_policy):
        self._presentation_policy[type] = presentation_policy

    def __find_template_file(self, name, relative_path=None):
        base_dir = path.dirname(path.abspath(__file__))
        file_path = path.join(base_dir, HtmlLogConfig.__FRAMEWORK_T_FOLDER)
        if relative_path is not None:
            file_path = path.join(file_path, relative_path)
        file_path = path.join(file_path, name)
        if path.isfile(file_path):
            return file_path
        else:
            raise Exception(
                f"Unable to find file: {name} in location: {os.path.dirname(file_path)}")

    def __get_main_template_file_path(self):
        return self.__find_template_file(HtmlLogConfig.MAIN)

    def _get_setup_template_file_path(self):
        return self.__find_template_file(HtmlLogConfig.SETUP, HtmlLogConfig.ITERATION_FOLDER)

    def __get_iteration_template_path(self):
        return self.__find_template_file(HtmlLogConfig.__T_ITERATION + '.html',
                                         HtmlLogConfig.ITERATION_FOLDER)

    def create_html_test_log(self, test_title):
        now = datetime.now()
        time_stamp = f"{now.year}_{str(now.month).zfill(2)}_{str(now.day).zfill(2)}_" \
            f"{str(now.hour).zfill(2)}_{str(now.minute).zfill(2)}_{str(now.second).zfill(2)}"
        self._log_dir = path.join(self._log_base_dir, test_title, time_stamp)
        makedirs(self._log_dir)
        additional_location = path.join(self._log_dir, HtmlLogConfig.ITERATION_FOLDER)
        makedirs(additional_location)
        dut_info_folder = path.join(self._log_dir, 'dut_info')
        makedirs(dut_info_folder)
        main_html = self.__get_main_template_file_path()
        main_css = main_html.replace('html', 'css')
        main_js = main_html.replace('html', 'js')
        copyfile(main_html, path.join(self._log_dir, HtmlLogConfig.MAIN))
        copyfile(main_css, path.join(self._log_dir, HtmlLogConfig.CSS))
        copyfile(main_js, path.join(self._log_dir, HtmlLogConfig.JS))
        copyfile(self._get_setup_template_file_path(), path.join(additional_location,
                                                                 HtmlLogConfig.SETUP))
        return self._log_dir

    def get_main_file_path(self):
        return path.join(self._log_dir, HtmlLogConfig.MAIN)

    def get_setup_file_path(self):
        return path.join(self._log_dir, HtmlLogConfig.ITERATION_FOLDER, HtmlLogConfig.SETUP)

    def create_iteration_file(self):
        self._iteration_id += 1
        template_file = self.__get_iteration_template_path()
        new_file_name = self.iteration()
        result = path.join(self._log_dir, HtmlLogConfig.ITERATION_FOLDER, new_file_name)
        copyfile(template_file, result)
        return result

    def end_iteration(self,
                      iteration_selector_div,
                      iteration_selector_select,
                      iteration_id,
                      iteration_result):
        style = "iteration-selector"
        if iteration_result != BaseLogResult.PASSED:
            style = f'{style} {HtmlLogConfig.STYLE[iteration_result]}'
        if iteration_id and iteration_id % 8 == 0:
            new_element = Element("br")
            iteration_selector_div[0].append(new_element)
        new_element = Element("a")
        new_element.set('class', style)
        new_element.set('onclick', f"selectIteration('{iteration_id}')")
        new_element.text = str(iteration_id)
        iteration_selector_div[0].append(new_element)
        new_element = Element('option', value=f"{iteration_id}")
        new_element.text = 'iteration_' + str(iteration_id).zfill(3)
        if iteration_result != BaseLogResult.PASSED:
            new_element.set('class', HtmlLogConfig.STYLE[iteration_result])
        iteration_selector_select.append(new_element)

    def end_setup_iteration(self, iteration_selector_div, iteration_selector_select, log_result):
        if log_result != BaseLogResult.PASSED:
            a_element = iteration_selector_div[0]
            select_element = iteration_selector_select[0]
            a_element.set('class', f'iteration-selector {HtmlLogConfig.STYLE[log_result]}')
            select_element.set('class', HtmlLogConfig.STYLE[log_result])

    def end_iteration_func(self, time_node, status_node, time_in_sec, log_result):
        time_node.text = f"Execution time: {convert_seconds_to_str(time_in_sec)}"
        status_node.text = f"Iteration status: {log_result.name}"
        if log_result != BaseLogResult.PASSED:
            status_node.set('class', f'iteration-status {HtmlLogConfig.STYLE[log_result]}')

    def end_main_log(self, test_status_div, log_result):
        if log_result != BaseLogResult.PASSED:
            test_status_div[0].set('class',
                                   f"sidebar-test-status {HtmlLogConfig.STYLE[log_result]}")
        test_status_div[0].text = f"Test status: {log_result.name}"

    def group_end(self, msg_id, html_header, html_container, log_result):
        html_header.set('onclick', f"showHide('ul_{msg_id}')")
        sub_element = Element('a', href="#top")
        sub_element.text = "[TOP]"
        sub_element.set('class', "top-time-marker")
        html_header.append(sub_element)
        div_style = 'test-group-step'
        ul_style = 'iteration-content'
        if log_result == BaseLogResult.PASSED:
            html_container.set('style', "display: none;")
        else:
            div_style = f"{div_style} {HtmlLogConfig.STYLE[log_result]}"
            ul_style = f"{ul_style} {HtmlLogConfig.STYLE[log_result]}"
        html_header.set('class', div_style)
        html_container.set('class', ul_style)

    def group_chapter_end(self, time_in_sec, html_header, html_container, log_result):
        sub_element = Element('a')
        sub_element.text = convert_seconds_to_str(time_in_sec)
        sub_element.set('class', 'top-marker')
        html_header.append(sub_element)
        div_style = 'test-group-step'
        ul_style = 'iteration-content'
        if log_result != BaseLogResult.PASSED:
            div_style = f"{div_style} {HtmlLogConfig.STYLE[log_result]}"
            ul_style = f"{ul_style} {HtmlLogConfig.STYLE[log_result]}"
        html_header.set('class', div_style)
        html_container.set('class', ul_style)
