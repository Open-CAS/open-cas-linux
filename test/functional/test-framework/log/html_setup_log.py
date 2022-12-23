#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.html_file_item_log import HtmlFileItemLog
from log.base_log import BaseLogResult


class HtmlSetupLog(HtmlFileItemLog):

    LOG_RESULT = {
        BaseLogResult.PASSED: HtmlFileItemLog.info,
        BaseLogResult.WORKAROUND: HtmlFileItemLog.workaround,
        BaseLogResult.WARNING: HtmlFileItemLog.warning,
        BaseLogResult.SKIPPED: HtmlFileItemLog.skip,
        BaseLogResult.FAILED: HtmlFileItemLog.error,
        BaseLogResult.BLOCKED: HtmlFileItemLog.blocked,
        BaseLogResult.EXCEPTION: HtmlFileItemLog.exception,
        BaseLogResult.CRITICAL: HtmlFileItemLog.critical}

    def __init__(self, test_title, config, iteration_title="Test summary"):
        html_file_path = config.get_setup_file_path()
        super().__init__(html_file_path, test_title, config, iteration_title)
        self._last_iteration_title = ''

    def start_iteration(self, message):
        self._last_iteration_title = message

    def end_iteration(self, iteration_result):
        HtmlSetupLog.LOG_RESULT[iteration_result](self, self._last_iteration_title)

    def end(self):
        super().end()
