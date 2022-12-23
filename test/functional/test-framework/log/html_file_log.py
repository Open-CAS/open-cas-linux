#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from log.base_log import BaseLog
from lxml.html import fromstring
from lxml.html import tostring


class HtmlFileLog(BaseLog):
    def __init__(self, file_path, title):
        super().__init__(title)
        self.__path = file_path
        with open(file_path) as file_stream:
            self.__root = fromstring(file_stream.read())
        node_list = self.__root.xpath('/html/head/title')
        node_list[0].text = title

    def get_path(self):
        return self.__path

    def get_root(self):
        return self.__root

    def end(self):
        with open(self.__path, "wb") as file:
            x = tostring(self.__root)
            file.write(x)
