#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import logging

LOGGER = logging.getLogger(__name__)

casadm_bin = "casadm"
casctl = "casctl"


def start_cmd(
    cache_dev: str,
    cache_mode: str = None,
    cache_line_size: str = None,
    cache_id: str = None,
    force: bool = False,
    load: bool = False,
    shortcut: bool = False,
) -> str:
    command = " -S" if shortcut else " --start-cache"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    if cache_mode is not None:
        command += (" -c " if shortcut else " --cache-mode ") + cache_mode
    if cache_line_size is not None:
        command += (" -x " if shortcut else " --cache-line-size ") + cache_line_size
    if cache_id is not None:
        command += (" -i " if shortcut else " --cache-id ") + cache_id
    if force:
        command += " -f" if shortcut else " --force"
    if load:
        command += " -l" if shortcut else " --load"
    return casadm_bin + command


def load_cmd(cache_dev: str, shortcut: bool = False) -> str:
    return start_cmd(cache_dev=cache_dev, load=True, shortcut=shortcut)


def attach_cache_cmd(
    cache_dev: str, cache_id: str, force: bool = False, shortcut: bool = False
) -> str:
    command = " --attach-cache"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def detach_cache_cmd(cache_id: str, shortcut: bool = False) -> str:
    command = " --detach-cache"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def stop_cmd(cache_id: str, no_data_flush: bool = False, shortcut: bool = False) -> str:
    command = " -T" if shortcut else " --stop-cache"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if no_data_flush:
        command += " --no-data-flush"
    return casadm_bin + command


def _set_param_cmd(name: str, cache_id: str, shortcut: bool = False) -> str:
    command = (" X -n" if shortcut else " --set-param --name ") + name
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return command


def set_param_cutoff_cmd(
    cache_id: str,
    core_id: str = None,
    threshold: str = None,
    policy: str = None,
    promotion_count: str = None,
    shortcut: bool = False,
) -> str:
    name = "seq-cutoff"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    if core_id:
        command += (" -j " if shortcut else " --core-id ") + core_id
    if threshold:
        command += (" -t " if shortcut else " --threshold ") + threshold
    if policy:
        command += (" -p " if shortcut else " --policy ") + policy
    if promotion_count:
        command += " --promotion-count " + promotion_count
    return casadm_bin + command


def set_param_promotion_cmd(cache_id: str, policy: str, shortcut: bool = False) -> str:
    name = "promotion"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    command += (" -p " if shortcut else " --policy ") + policy
    return casadm_bin + command


def set_param_promotion_nhit_cmd(
    cache_id: str, threshold: str = None, trigger: str = None, shortcut: bool = False
) -> str:
    name = "promotion-nhit"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    if threshold:
        command += (" -t " if shortcut else " --threshold ") + threshold
    if trigger is not None:
        command += (" -o " if shortcut else " --trigger ") + trigger
    return casadm_bin + command


def set_param_cleaning_cmd(cache_id: str, policy: str, shortcut: bool = False) -> str:
    name = "cleaning"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    command += (" -p " if shortcut else " --policy ") + policy
    return casadm_bin + command


def set_param_cleaning_alru_cmd(
    cache_id: str,
    wake_up: str = None,
    staleness_time: str = None,
    flush_max_buffers: str = None,
    activity_threshold: str = None,
    shortcut: bool = False,
) -> str:
    name = "cleaning-alru"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    if wake_up:
        command += (" -w " if shortcut else " --wake-up ") + wake_up
    if staleness_time:
        command += (" -s " if shortcut else " --staleness-time ") + staleness_time
    if flush_max_buffers:
        command += (" -b " if shortcut else " --flush-max-buffers ") + flush_max_buffers
    if activity_threshold:
        command += (" -t " if shortcut else " --activity-threshold ") + activity_threshold
    return casadm_bin + command


def set_param_cleaning_acp_cmd(
    cache_id: str,
    wake_up: str = None,
    flush_max_buffers: str = None,
    shortcut: bool = False,
) -> str:
    name = "cleaning-acp"
    command = _set_param_cmd(name=name, cache_id=cache_id, shortcut=shortcut)
    if wake_up is not None:
        command += (" -w " if shortcut else " --wake-up ") + wake_up
    if flush_max_buffers is not None:
        command += (" -b " if shortcut else " --flush-max-buffers ") + flush_max_buffers
    return casadm_bin + command


def _get_param_cmd(
    name: str,
    cache_id: str,
    output_format: str = None,
    shortcut: bool = False,
) -> str:
    command = (" -G -n" if shortcut else " --get-param --name ") + name
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if output_format:
        command += (" -o " if shortcut else " --output-format ") + output_format
    return command


def get_param_cutoff_cmd(
    cache_id: str, core_id: str, output_format: str = None, shortcut: bool = False
) -> str:
    name = "seq-cutoff"
    command = _get_param_cmd(
        name=name,
        cache_id=cache_id,
        core_id=core_id,
        output_format=output_format,
        shortcut=shortcut,
    )
    command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def get_param_cleaning_cmd(cache_id: str, output_format: str = None, shortcut: bool = False) -> str:
    name = "cleaning"
    command = _get_param_cmd(
        name=name, cache_id=cache_id, output_format=output_format, shortcut=shortcut
    )
    return casadm_bin + command


def get_param_cleaning_alru_cmd(
    cache_id: str, output_format: str = None, shortcut: bool = False
) -> str:
    name = "cleaning-alru"
    command = _get_param_cmd(
        name=name, cache_id=cache_id, output_format=output_format, shortcut=shortcut
    )
    return casadm_bin + command


def get_param_cleaning_acp_cmd(
    cache_id: str, output_format: str = None, shortcut: bool = False
) -> str:
    name = "cleaning-acp"
    command = _get_param_cmd(
        name=name, cache_id=cache_id, output_format=output_format, shortcut=shortcut
    )
    return casadm_bin + command


def set_cache_mode_cmd(
    cache_mode: str, cache_id: str, flush_cache: str = None, shortcut: bool = False
) -> str:
    command = (" -Q -c" if shortcut else " --set-cache-mode --cache-mode ") + cache_mode
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if flush_cache:
        command += (" -f " if shortcut else " --flush-cache ") + flush_cache
    return casadm_bin + command


def add_core_cmd(cache_id: str, core_dev: str, core_id: str = None, shortcut: bool = False) -> str:
    command = " -A " if shortcut else " --add-core"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -d " if shortcut else " --core-device ") + core_dev
    if core_id:
        command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def remove_core_cmd(
    cache_id: str, core_id: str, force: bool = False, shortcut: bool = False
) -> str:
    command = " -R " if shortcut else " --remove-core"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -j " if shortcut else " --core-id ") + core_id
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def remove_inactive_cmd(
    cache_id: str, core_id: str, force: bool = False, shortcut: bool = False
) -> str:
    command = " --remove-inactive"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -j " if shortcut else " --core-id ") + core_id
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def remove_detached_cmd(core_device: str, shortcut: bool = False) -> str:
    command = " --remove-detached"
    command += (" -d " if shortcut else " --device ") + core_device
    return casadm_bin + command


def list_caches_cmd(
    output_format: str = None, by_id_path: bool = True, shortcut: bool = False
) -> str:
    command = " -L" if shortcut else " --list-caches"
    if output_format:
        command += (" -o " if shortcut else " --output-format ") + output_format
    if by_id_path:
        command += " -b" if shortcut else " --by-id-path"
    return casadm_bin + command


def print_statistics_cmd(
    cache_id: str,
    core_id: str = None,
    io_class_id: str = None,
    filter: str = None,
    output_format: str = None,
    by_id_path: bool = True,
    shortcut: bool = False,
) -> str:
    command = " -P" if shortcut else " --stats"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if core_id:
        command += (" -j " if shortcut else " --core-id ") + core_id
    if io_class_id:
        command += (" -d " if shortcut else " --io-class-id ") + io_class_id
    if filter:
        command += (" -f " if shortcut else " --filter ") + filter
    if output_format:
        command += (" -o " if shortcut else " --output-format ") + output_format
    if by_id_path:
        command += " -b " if shortcut else " --by-id-path "
    return casadm_bin + command


def reset_counters_cmd(cache_id: str, core_id: str = None, shortcut: bool = False) -> str:
    command = " -Z" if shortcut else " --reset-counters"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if core_id is not None:
        command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def flush_cache_cmd(cache_id: str, shortcut: bool = False) -> str:
    command = " -F" if shortcut else " --flush-cache"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def flush_core_cmd(cache_id: str, core_id: str, shortcut: bool = False) -> str:
    command = " -F" if shortcut else " --flush-cache"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def load_io_classes_cmd(cache_id: str, file: str, shortcut: bool = False) -> str:
    command = " -C -C" if shortcut else " --io-class --load-config"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -f " if shortcut else " --file ") + file
    return casadm_bin + command


def list_io_classes_cmd(cache_id: str, output_format: str, shortcut: bool = False) -> str:
    command = " -C -L" if shortcut else " --io-class --list"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -o " if shortcut else " --output-format ") + output_format
    return casadm_bin + command


def version_cmd(output_format: str = None, shortcut: bool = False) -> str:
    command = " -V" if shortcut else " --version"
    if output_format:
        command += (" -o " if shortcut else " --output-format ") + output_format
    return casadm_bin + command


def help_cmd(shortcut: bool = False) -> str:
    command = " -H" if shortcut else " --help"
    return casadm_bin + command


def standby_init_cmd(
    cache_dev: str,
    cache_id: str,
    cache_line_size: str,
    force: bool = False,
    shortcut: bool = False,
) -> str:
    command = " --standby --init"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -x " if shortcut else " --cache-line-size ") + cache_line_size
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def standby_load_cmd(cache_dev: str, shortcut: bool = False) -> str:
    command = " --standby --load"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    return casadm_bin + command


def standby_detach_cmd(cache_id: str, shortcut: bool = False) -> str:
    command = " --standby --detach"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def standby_activate_cmd(cache_dev: str, cache_id: str, shortcut: bool = False) -> str:
    command = " --standby --activate"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def zero_metadata_cmd(cache_dev: str, force: bool = False, shortcut: bool = False) -> str:
    command = " --zero-metadata"
    command += (" -d " if shortcut else " --device ") + cache_dev
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


# casctl command


def ctl_help(shortcut: bool = False) -> str:
    command = " --help" if shortcut else " -h"
    return casctl + command


def ctl_start() -> str:
    command = " start"
    return casctl + command


def ctl_stop(flush: bool = False) -> str:
    command = " stop"
    if flush:
        command += " --flush"
    return casctl + command


def ctl_init(force: bool = False) -> str:
    command = " init"
    if force:
        command += " --force"
    return casctl + command


# casadm script


def script_try_add_cmd(cache_id: str, core_dev: str, core_id: str = None) -> str:
    command = " --script --add-core --try-add"
    command += " --cache-id " + cache_id
    if core_id:
        command += " --core-device " + core_dev
    return casadm_bin + command


def script_purge_cache_cmd(cache_id: str) -> str:
    command = "--script --purge-cache"
    command += " --cache-id " + cache_id
    return casadm_bin + command


def script_purge_core_cmd(cache_id: str, core_id: str) -> str:
    command = "--script --purge-core"
    command += " --cache-id " + cache_id
    command += " --core-id " + core_id
    return casadm_bin + command


def script_detach_core_cmd(cache_id: str, core_id: str) -> str:
    command = "--script --remove-core --detach"
    command += " --cache-id " + cache_id
    command += " --core-id " + core_id
    return casadm_bin + command


def script_remove_core_cmd(cache_id: str, core_id: str, no_flush: bool = False) -> str:
    command = "--script --remove-core"
    command += " --cache-id " + cache_id
    command += " --core-id " + core_id
    if no_flush:
        command += " --no-flush"
    return casadm_bin + command
