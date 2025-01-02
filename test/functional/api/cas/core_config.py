#
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from enum import Enum


class CoreStatus(Enum):
    empty = "empty"
    active = "active"
    inactive = "inactive"
    detached = "detached"

    def __str__(self):
        return self.value
