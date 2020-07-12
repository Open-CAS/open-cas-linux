#
# Copyright(c) 2019-2020 Intel Corporation
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

get_stats_ioclass_id_not_configured = [
    r"IO class \d+ is not configured\."
]

get_stats_ioclass_id_out_of_range = [
    r"Invalid IO class id, must be in the range 0-32\."
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

load_and_force = [
    r"Use of \'load\' and \'force\' simultaneously is forbidden\."
]

try_add_core_sector_size_mismatch = [
    r"Error while adding core device to cache instance \d+",
    r"Cache device logical sector size is greater than core device logical sector size\.",
    r"Consider changing logical sector size on current cache device",
    r"or try other device with the same logical sector size as core device\."
]


def check_stderr_msg(output: Output, expected_messages):
    return __check_string_msg(output.stderr, expected_messages)


def check_stdout_msg(output: Output, expected_messages):
    return __check_string_msg(output.stdout, expected_messages)


def __check_string_msg(text: str, expected_messages):
    msg_ok = True
    for msg in expected_messages:
        matches = re.search(msg, text)
        if not matches:
            TestRun.LOGGER.error(f"Message is incorrect, expected: {msg}\n actual: {text}.")
            msg_ok = False
    return msg_ok
