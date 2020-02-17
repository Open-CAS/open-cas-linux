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

start_cache_with_existing_metadata = [
    r"Error inserting cache \d+",
    r"Old metadata found on device\.",
    r"Please load cache metadata using --load option or use --force to",
    r" discard on-disk metadata and start fresh cache instance\.",
    r"Error occurred, please see syslog \(/var/log/messages\) for details\."
]

remove_inactive_core = [
    r"Error while removing core device \d+ from cache instance \d+",
    r"Core device is in inactive state"
]

stop_cache_incomplete = [
    r"Error while removing cache \d+",
    r"Cache is in incomplete state - at least one core is inactive"
]

remove_multilevel_core = [
    r"Error while removing core device \d+ from cache instance \d+",
    r"Device opens or mount are pending to this cache"
]

add_cached_core = [
    r"Error while adding core device to cache instance \d+",
    r"Core device \'/dev/\S+\' is already cached\."
]

remove_mounted_core = [
    r"Can\'t remove core \d+ from cache \d+\. Device /dev/cas\d+-\d+ is mounted\!"
]

stop_cache_mounted_core = [
    r"Can\'t stop cache instance \d+\. Device /dev/cas\d+-\d+ is mounted\!"
]


def check_msg(output: Output, expected_messages):
    result = '\n'.join([output.stdout, output.stderr])
    for msg in expected_messages:
        matches = re.search(msg, result)
        if not matches:
            TestRun.LOGGER.error(f"Message is incorrect, expected: {msg}\n actual: {result}.")
