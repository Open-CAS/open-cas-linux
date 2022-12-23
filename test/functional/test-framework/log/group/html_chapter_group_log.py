#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.base_log import BaseLogResult, BaseLog
from log.group.html_group_log import HtmlGroupLog
from datetime import datetime


class HtmlChapterGroupLog(HtmlGroupLog):
    SET_RESULT = {
        BaseLogResult.PASSED: BaseLog.info,
        BaseLogResult.WORKAROUND: BaseLog.workaround,
        BaseLogResult.WARNING: BaseLog.warning,
        BaseLogResult.SKIPPED: BaseLog.skip,
        BaseLogResult.FAILED: BaseLog.error,
        BaseLogResult.BLOCKED: BaseLog.blocked,
        BaseLogResult.EXCEPTION: BaseLog.exception,
        BaseLogResult.CRITICAL: BaseLog.critical}

    def __init__(self, html_base, cfg, begin_msg=None, id='ch0'):
        super().__init__(HtmlChapterGroupLog._factory, html_base, cfg, begin_msg, id)

    @staticmethod
    def _factory(html_base, cfg, begin_msg, id):
        return HtmlChapterGroupLog(html_base, cfg, begin_msg, id)

    def end_dir_group(self, ref_group):
        group = super().end_group()
        ref_container_id = ref_group._container.get('id')
        group._header.set('ondblclick', f"chapterClick('{ref_container_id}')")

    def set_result(self, result):
        if self._successor is not None:
            self._successor.set_result(result)
        HtmlChapterGroupLog.SET_RESULT[result](self, "set result")

    def end(self):
        result = super().end()
        exe_time = (datetime.now() - self._start_time).seconds
        self._cfg.group_chapter_end(exe_time, self._header, self._container, result)
        return result
