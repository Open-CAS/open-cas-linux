#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import re

from core.test_run import TestRun
from test_utils.output import Output

load_inactive_core_missing = [
    r"WARNING: Can not resolve path to core \d+ from cache \d+\. By-id path will be shown for that "
    r"core\.",
    r"WARNING: Cache is in incomplete state - at least one core is inactive",
]

start_cache_with_existing_metadata = [
    r"Error inserting cache \d+",
    r"Old metadata found on device\.",
    r"Please load cache metadata using --load option or use --force to",
    r" discard on-disk metadata and start fresh cache instance\."
]

error_inserting_cache = [
    r"Error inserting cache \d+"
]

reinitialize_with_force_or_recovery = [
    r"Old metadata found on device\.",
    r"Please load cache metadata using --load option or use --force to",
    r" discard on-disk metadata and start fresh cache instance\."
]

remove_inactive_core_with_remove_command = [
    r"Core is inactive\. To manage the inactive core use '--remove-inactive' command\."
]

remove_inactive_dirty_core = [
    r"The cache contains dirty data assigned to the core\. If you want to ",
    r"continue, please use --force option\.\nWarning: the data will be lost"
]

stop_cache_incomplete = [
    r"Error while removing cache \d+",
    r"Cache is in incomplete state - at least one core is inactive"
]

stop_cache_errors = [
    r"Removed cache \d+ with errors",
    r"Error while writing to cache device"
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

already_cached_core = [
    r"Error while adding core device to cache instance \d+",
    r"Device already added as a core"
]

remove_mounted_core = [
    r"Can\'t remove core \d+ from cache \d+\. Device /dev/cas\d+-\d+ is mounted\!"
]

stop_cache_mounted_core = [
    r"Can\'t stop cache instance \d+\. Device /dev/cas\d+-\d+ is mounted\!"
]

load_and_force = [
    r"Use of \'load\' with \'force\', \'cache-id\', \'cache-mode\' or \'cache-line-size\'",
    r" simultaneously is forbidden."
]

try_add_core_sector_size_mismatch = [
    r"Error while adding core device to cache instance \d+",
    r"Cache device logical sector size is greater than core device logical sector size\.",
    r"Consider changing logical sector size on current cache device",
    r"or try other device with the same logical sector size as core device\."
]

no_caches_running = [
    r"No caches running"
]

unavailable_device = [
    r"Error while opening \'\S+\'exclusively\. This can be due to\n"
    r"cache instance running on this device\. In such case please stop the cache and try again\."
]

error_handling = [
    r"Error during options handling"
]

no_cas_metadata = [
    r"Device \'\S+\' does not contain OpenCAS's metadata\."
]

cache_dirty_data = [
    r"Cache instance contains dirty data\. Clearing metadata will result in loss of dirty data\.\n"
    r"Please load cache instance and flush dirty data in order to preserve them on the core "
    r"device\.\n"
    r"Alternatively, if you wish to clear metadata anyway, please use \'--force\' option\."
]

cache_dirty_shutdown = [
    r"Cache instance did not shut down cleanly\. It might contain dirty data\. \n"
    r"Clearing metadata might result in loss of dirty data\. Please recover cache instance\n"
    r"by loading it and flush dirty data in order to preserve them on the core device\.\n"
    r"Alternatively, if you wish to clear metadata anyway, please use \'--force\' option\."
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
