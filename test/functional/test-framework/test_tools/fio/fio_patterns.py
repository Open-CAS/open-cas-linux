#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import secrets
from aenum import Enum


class Pattern(Enum):
    cyclic = "0x00336699ccffcc996633"
    sequential = "0x" + "".join([f"{i:02x}" for i in range(0, 256)])
    high = "0xaa"
    low = "0x84210"
    zeroes = "0x00"
    ones = "0xff"
    bin_1 = high
    bin_2 = "0x55"
    random = "0x" + secrets.token_hex()
