#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from attotime import attotimedelta


class Time(attotimedelta):
    def total_microseconds(self):
        return self.total_nanoseconds() / 1_000

    def total_milliseconds(self):
        return self.total_nanoseconds() / 1_000_000
