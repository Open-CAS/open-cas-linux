#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from enum import Enum


class OutputFormat(Enum):
    table = 0
    csv = 1


class StatsFilter(Enum):
    all = 0
    conf = 1
    usage = 2
    req = 3
    blk = 4
    err = 5
