#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
import re

from core.test_run import TestRun
from test_utils.output import Output


load_inactive_core_missing = [
    r"WARNING: Can not resolve path to core \d+ from cache \d+\. By-id path will be shown for that "
    r"core\.",
    r"WARNING: Cache is in incomplete state - at least one core is inactive",
    r"Successfully added cache instance \d+"
]

remove_inactive_core = [
    r"Error while removing core device \d+ from cache instance \d+",
    r"Core device is in inactive state"
]

stop_cache_incomplete = [
    r"Error while removing cache \d+",
    r"Cache is in incomplete state - at least one core is inactive"
]


def check_msg(output: Output, expected_messages):
    result = '\n'.join([output.stdout, output.stderr])
    for msg in expected_messages:
        matches = re.search(msg, result)
        if not matches:
            TestRun.fail(f"Message is incorrect, expected: {msg}\n actual: {result}.")
