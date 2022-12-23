#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.html_file_item_log import HtmlFileItemLog


class HtmlIterationLog(HtmlFileItemLog):
    def __init__(self, test_title, iteration_title, config):
        self.iteration_closed: bool = False
        html_file = config.create_iteration_file()
        super().__init__(html_file, test_title, config, iteration_title)
