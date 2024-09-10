#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from enum import Enum


class ParamName(Enum):
    seq_cutoff = "seq-cutoff"
    cleaning = "cleaning"
    cleaning_alru = "cleaning-alru"
    cleaning_acp = "cleaning-acp"
    promotion = "promotion"
    promotion_nhit = "promotion-nhit"

    def __str__(self):
        return self.value


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
