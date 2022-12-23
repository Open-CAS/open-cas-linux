#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import string


def random_string(length: int, chars=string.ascii_letters + string.digits):
    return ''.join(random.choice(chars) for i in range(length))
