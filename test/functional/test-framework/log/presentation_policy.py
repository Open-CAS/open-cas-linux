#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


class PresentationPolicy:
    def __init__(self, standard_log, group_begin_func):
        self.standard = standard_log
        self.group_begin = group_begin_func


def std_log_entry(msg_id, msg, log_result, html_node):
    pass


def group_log_begin(msg_id, msg, html_node):
    return html_node, html_node


null_policy = PresentationPolicy(std_log_entry, group_log_begin)
