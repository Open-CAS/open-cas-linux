#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from api.cas.cli_messages import __check_string_msg
from core.test_run import TestRun


interrupt_stop = [
    r"Waiting for cache stop interrupted\. Stop will finish asynchronously\."
]

interrupt_start = [
    r"Cache added successfully, but waiting interrupted\. Rollback"
]

load_and_force = [
    r"cache\d+: Using \'force\' flag is forbidden for load operation\."
]


def clear_dmesg():
    TestRun.executor.run_expect_success('dmesg -C')


def check_dmesg(searched_phrase: str):
    dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout
    __check_string_msg(dmesg_out, searched_phrase)
