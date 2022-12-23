#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from connection.base_executor import BaseExecutor


class DummyExecutor(BaseExecutor):
    def _execute(self, command, timeout=None):
        print(command)

    def _rsync(self, src, dst, delete, symlinks, checksum, exclude_list, timeout,
               dut_to_controller):
        print(f'COPY FROM "{src}" TO "{dst}"')
