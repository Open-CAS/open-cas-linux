#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import logging

LOGGER = logging.getLogger(__name__)

casadm_bin = "casadm"
casctl = "casctl"


def add_core_cmd(cache_id: str, core_dev: str, core_id: str = None, shortcut: bool = False):
    command = f" -A -i {cache_id} -d {core_dev}" if shortcut \
        else f" --add-core --cache-id {cache_id} --core-device {core_dev}"
    if core_id is not None:
        command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def script_try_add_cmd(cache_id: str, core_dev: str, core_id: str = None):
    command = f"{casadm_bin} --script --add-core --try-add --cache-id {cache_id} " \
              f"--core-device {core_dev}"
    if core_id:
        command += f" --core-id {core_id}"
    return command


def script_purge_cache_cmd(cache_id: str):
    return f"{casadm_bin} --script --purge-cache --cache-id {cache_id}"


def script_purge_core_cmd(cache_id: str, core_id: str):
    return f"{casadm_bin} --script --purge-core --cache-id {cache_id} --core-id {core_id}"


def script_detach_core_cmd(cache_id: str, core_id: str):
    return f"{casadm_bin} --script --remove-core --detach --cache-id {cache_id} " \
           f"--core-id {core_id}"


def script_remove_core_cmd(cache_id: str, core_id: str, no_flush: bool = False):
    command = f"{casadm_bin} --script --remove-core --cache-id {cache_id} --core-id {core_id}"
    if no_flush:
        command += ' --no-flush'
    return command


def remove_core_cmd(cache_id: str, core_id: str, force: bool = False, shortcut: bool = False):
    command = f" -R -i {cache_id} -j {core_id}" if shortcut \
        else f" --remove-core --cache-id {cache_id} --core-id {core_id}"
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def remove_inactive_cmd(cache_id: str, core_id: str, force: bool = False, shortcut: bool = False):
    command = f" --remove-inactive {'-i' if shortcut else '--cache-id'} {cache_id} " \
              f"{'-j' if shortcut else '--core-id'} {core_id}"
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def remove_detached_cmd(core_device: str, shortcut: bool = False):
    command = " --remove-detached" + (" -d " if shortcut else " --device ") + core_device
    return casadm_bin + command


def help_cmd(shortcut: bool = False):
    return casadm_bin + (" -H" if shortcut else " --help")


def reset_counters_cmd(cache_id: str, core_id: str = None, shortcut: bool = False):
    command = (" -Z -i " if shortcut else " --reset-counters --cache-id ") + cache_id
    if core_id is not None:
        command += (" -j " if shortcut else " --core-id ") + core_id
    return casadm_bin + command


def flush_cache_cmd(cache_id: str, shortcut: bool = False):
    command = (" -F -i " if shortcut else " --flush-cache --cache-id ") + cache_id
    return casadm_bin + command


def flush_core_cmd(cache_id: str, core_id: str, shortcut: bool = False):
    command = (f" -E -i {cache_id} -j {core_id}" if shortcut
               else f" --flush-core --cache-id {cache_id} --core-id {core_id}")
    return casadm_bin + command


def start_cmd(cache_dev: str, cache_mode: str = None, cache_line_size: str = None,
              cache_id: str = None, force: bool = False,
              load: bool = False, shortcut: bool = False):
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


def standby_init_cmd(cache_dev: str, cache_id: str, cache_line_size: str,
                     force: bool = False, shortcut: bool = False):
    command = " --standby --init"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    command += (" -x " if shortcut else " --cache-line-size ") + cache_line_size
    if force:
        command += " -f" if shortcut else " --force"
    return casadm_bin + command


def standby_load_cmd(cache_dev: str, shortcut: bool = False):
    command = " --standby --load"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    return casadm_bin + command


def standby_detach_cmd(cache_id: str, shortcut: bool = False):
    command = " --standby --detach"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def standby_activate_cmd(cache_dev: str, cache_id: str, shortcut: bool = False):
    command = " --standby --activate"
    command += (" -d " if shortcut else " --cache-device ") + cache_dev
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    return casadm_bin + command


def print_statistics_cmd(cache_id: str, core_id: str = None, per_io_class: bool = False,
                         io_class_id: str = None, filter: str = None,
                         output_format: str = None, by_id_path: bool = True,
                         shortcut: bool = False):
    command = (" -P -i " if shortcut else " --stats --cache-id ") + cache_id
    if core_id is not None:
        command += (" -j " if shortcut else " --core-id ") + core_id
    if per_io_class:
        command += " -d" if shortcut else " --io-class-id"
        if io_class_id is not None:
            command += " " + io_class_id
    elif io_class_id is not None:
        raise Exception("Per io class flag not set but ID given.")
    if filter is not None:
        command += (" -f " if shortcut else " --filter ") + filter
    if output_format is not None:
        command += (" -o " if shortcut else " --output-format ") + output_format
    if by_id_path:
        command += (" -b " if shortcut else " --by-id-path ")
    return casadm_bin + command


def zero_metadata_cmd(cache_dev: str, force: bool = False, shortcut: bool = False):
    command = " --zero-metadata"
    command += (" -d " if shortcut else " --device ") + cache_dev
    if force:
        command += (" -f" if shortcut else " --force")
    return casadm_bin + command


def stop_cmd(cache_id: str, no_data_flush: bool = False, shortcut: bool = False):
    command = " -T " if shortcut else " --stop-cache"
    command += (" -i " if shortcut else " --cache-id ") + cache_id
    if no_data_flush:
        command += " --no-data-flush"
    return casadm_bin + command


def list_cmd(output_format: str = None, by_id_path: bool = True, shortcut: bool = False):
    command = " -L" if shortcut else " --list-caches"
    if output_format == "table" or output_format == "csv":
        command += (" -o " if shortcut else " --output-format ") + output_format
    if by_id_path:
        command += (" -b " if shortcut else " --by-id-path ")
    return casadm_bin + command


def load_cmd(cache_dev: str, shortcut: bool = False):
    return start_cmd(cache_dev, load=True, shortcut=shortcut)


def version_cmd(output_format: str = None, shortcut: bool = False):
    command = " -V" if shortcut else " --version"
    if output_format == "table" or output_format == "csv":
        command += (" -o " if shortcut else " --output-format ") + output_format
    return casadm_bin + command


def set_cache_mode_cmd(cache_mode: str, cache_id: str,
                       flush_cache: str = None, shortcut: bool = False):
    command = f" -Q -c {cache_mode} -i {cache_id}" if shortcut else \
              f" --set-cache-mode --cache-mode {cache_mode} --cache-id {cache_id}"
    if flush_cache:
        command += (" -f " if shortcut else " --flush-cache ") + flush_cache
    return casadm_bin + command


def load_io_classes_cmd(cache_id: str, file: str, shortcut: bool = False):
    command = f" -C -C -i {cache_id} -f {file}" if shortcut else \
              f" --io-class --load-config --cache-id {cache_id} --file {file}"
    return casadm_bin + command


def list_io_classes_cmd(cache_id: str, output_format: str, shortcut: bool = False):
    command = f" -C -L -i {cache_id} -o {output_format}" if shortcut else \
              f" --io-class --list --cache-id {cache_id} --output-format {output_format}"
    return casadm_bin + command


def _get_param_cmd(namespace: str, cache_id: str, output_format: str = None,
                   additional_params: str = None, shortcut: bool = False):
    command = f" -G -n {namespace} -i {cache_id}" if shortcut else\
              f" --get-param --name {namespace} --cache-id {cache_id}"
    if additional_params is not None:
        command += additional_params
    if output_format is not None:
        command += (" -o " if shortcut else " --output-format ") + output_format
    return casadm_bin + command


def get_param_cutoff_cmd(cache_id: str, core_id: str,
                         output_format: str = None, shortcut: bool = False):
    add_param = (" -j " if shortcut else " --core-id ") + core_id
    return _get_param_cmd(namespace="seq-cutoff", cache_id=cache_id, output_format=output_format,
                          additional_params=add_param, shortcut=shortcut)


def get_param_cleaning_cmd(cache_id: str, output_format: str = None, shortcut: bool = False):
    return _get_param_cmd(namespace="cleaning", cache_id=cache_id,
                          output_format=output_format, shortcut=shortcut)


def get_param_cleaning_alru_cmd(cache_id: str, output_format: str = None, shortcut: bool = False):
    return _get_param_cmd(namespace="cleaning-alru", cache_id=cache_id,
                          output_format=output_format, shortcut=shortcut)


def get_param_cleaning_acp_cmd(cache_id: str, output_format: str = None, shortcut: bool = False):
    return _get_param_cmd(namespace="cleaning-acp", cache_id=cache_id,
                          output_format=output_format, shortcut=shortcut)


def _set_param_cmd(namespace: str, cache_id: str, additional_params: str = None,
                   shortcut: bool = False):
    command = f" -X -n {namespace} -i {cache_id}" if shortcut else\
              f" --set-param --name {namespace} --cache-id {cache_id}"
    command += additional_params
    return casadm_bin + command


def set_param_cutoff_cmd(cache_id: str, core_id: str = None, threshold: str = None,
                         policy: str = None, promotion_count: str = None, shortcut: bool = False):
    add_params = ""
    if core_id is not None:
        add_params += (" -j " if shortcut else " --core-id ") + str(core_id)
    if threshold is not None:
        add_params += (" -t " if shortcut else " --threshold ") + str(threshold)
    if policy is not None:
        add_params += (" -p " if shortcut else " --policy ") + policy
    if promotion_count is not None:
        add_params += " --promotion-count " + str(promotion_count)
    return _set_param_cmd(namespace="seq-cutoff", cache_id=cache_id,
                          additional_params=add_params, shortcut=shortcut)


def set_param_promotion_cmd(cache_id: str, policy: str, shortcut: bool = False):
    add_params = (" -p " if shortcut else " --policy ") + policy
    return _set_param_cmd(namespace="promotion", cache_id=cache_id,
                          additional_params=add_params, shortcut=shortcut)


def set_param_promotion_nhit_cmd(
    cache_id: str, threshold=None, trigger=None, shortcut: bool = False
):
    add_params = ""
    if threshold is not None:
        add_params += (" -t " if shortcut else " --threshold ") + str(threshold)
    if trigger is not None:
        add_params += (" -o " if shortcut else " --trigger ") + str(trigger)
    return _set_param_cmd(namespace="promotion-nhit", cache_id=cache_id,
                          additional_params=add_params, shortcut=shortcut)


def set_param_cleaning_cmd(cache_id: str, policy: str, shortcut: bool = False):
    add_params = (" -p " if shortcut else " --policy ") + policy
    return _set_param_cmd(namespace="cleaning", cache_id=cache_id,
                          additional_params=add_params, shortcut=shortcut)


def set_param_cleaning_alru_cmd(cache_id, wake_up=None, staleness_time=None,
                                flush_max_buffers=None, activity_threshold=None,
                                shortcut: bool = False):
    add_param = ""
    if wake_up is not None:
        add_param += (" -w " if shortcut else " --wake-up ") + str(wake_up)
    if staleness_time is not None:
        add_param += (" -s " if shortcut else " --staleness-time ") + str(staleness_time)
    if flush_max_buffers is not None:
        add_param += (" -b " if shortcut else " --flush-max-buffers ") + str(flush_max_buffers)
    if activity_threshold is not None:
        add_param += (" -t " if shortcut else " --activity-threshold ") + str(activity_threshold)

    return _set_param_cmd(namespace="cleaning-alru", cache_id=cache_id,
                          additional_params=add_param, shortcut=shortcut)


def set_param_cleaning_acp_cmd(cache_id: str, wake_up: str = None,
                               flush_max_buffers: str = None, shortcut: bool = False):
    add_param = ""
    if wake_up is not None:
        add_param += (" -w " if shortcut else " --wake-up ") + wake_up
    if flush_max_buffers is not None:
        add_param += (" -b " if shortcut else " --flush-max-buffers ") + flush_max_buffers
    return _set_param_cmd(namespace="cleaning-acp", cache_id=cache_id,
                          additional_params=add_param, shortcut=shortcut)


def ctl_help(shortcut: bool = False):
    return casctl + " --help" if shortcut else " -h"


def ctl_start():
    return casctl + " start"


def ctl_stop(flush: bool = False):
    command = casctl + " stop"
    if flush:
        command += " --flush"
    return command


def ctl_init(force: bool = False):
    command = casctl + " init"
    if force:
        command += " --force"
    return command
