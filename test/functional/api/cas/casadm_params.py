#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from aenum import Enum


class OutputFormat(Enum):
    table = 0
    csv = 1


class StatsFilter(Enum):
    all = "all"
    conf = "configuration"
    usage = "usage"
    req = "request"
    blk = "block"
    err = "error"

    def __str__(self):
        return self.value
