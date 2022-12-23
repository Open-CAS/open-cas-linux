#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import test_utils.linux_command as linux_comm
import test_utils.size as size
from core.test_run import TestRun


class Dd(linux_comm.LinuxCommand):
    def __init__(self):
        linux_comm.LinuxCommand.__init__(self, TestRun.executor, 'dd')

    def block_size(self, value: size.Size):
        return self.set_param('bs', int(value.get_value()))

    def count(self, value):
        return self.set_param('count', value)

    def input(self, value):
        return self.set_param('if', value)

    def iflag(self, *values):
        return self.set_param('iflag', *values)

    def oflag(self, *values):
        return self.set_param('oflag', *values)

    def conv(self, *values):
        return self.set_param('conv', *values)

    def output(self, value):
        return self.set_param('of', value)

    def seek(self, value):
        return self.set_param('seek', value)

    def skip(self, value):
        return self.set_param('skip', value)
