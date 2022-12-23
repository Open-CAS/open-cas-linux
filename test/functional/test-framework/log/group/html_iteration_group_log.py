#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.group.html_group_log import HtmlGroupLog


class HtmlIterationGroupLog(HtmlGroupLog):
    def __init__(self, html_base, cfg, begin_msg, id='itg0'):
        super().__init__(HtmlIterationGroupLog._factory, html_base, cfg, begin_msg, id)

    @staticmethod
    def _factory(html_base, cfg, begin_msg, id):
        return HtmlIterationGroupLog(html_base, cfg, begin_msg, id)

    def end(self):
        result = super().end()
        self._cfg.group_end(self._id, self._header, self._container, result)
        return result
