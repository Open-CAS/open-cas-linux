#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.base_log import BaseLogResult
from lxml.etree import Element
from datetime import datetime
from log.presentation_policy import PresentationPolicy
from log.html_log_config import HtmlLogConfig


def std_log_entry(msg_id, msg, log_result, html_node):
    test_step = Element('li')
    style = 'test-step'
    if log_result != BaseLogResult.PASSED:
        style = f"{style} {HtmlLogConfig.STYLE[log_result]}"
    test_step.set('class', style)
    test_time = Element('div')
    test_time.set('class', 'ts-time')
    test_time_txt = Element('a', name=msg_id)
    time = datetime.now()
    test_time_txt.text = f"{str(time.hour).zfill(2)}:" \
        f"{str(time.minute).zfill(2)}:{str(time.second).zfill(2)}"
    test_time.append(test_time_txt)
    test_step.append(test_time)
    test_msg = Element('div')
    test_msg.set('class', 'ts-msg')
    test_msg.text = msg
    test_step.append(test_msg)
    html_node.append(test_step)


def group_log_begin(msg_id, msg, html_node):
    element = Element("div")
    sub_element = Element('a', name=msg_id)
    sub_element.text = msg
    element.append(sub_element)
    html_node.append(element)
    ul_set = Element('ul', id=f'ul_{msg_id}')
    html_node.append(ul_set)
    return element, ul_set


html_policy = PresentationPolicy(std_log_entry, group_log_begin)
