#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from typing import List

from api.cas.cache import Cache
from api.cas.cache_config import CacheLineSize, CacheMode, SeqCutOffPolicy, CleaningPolicy
from api.cas.core import Core
from core.test_run import TestRun
from storage_devices.device import Device
from test_utils.output import CmdException
from test_utils.size import Size, Unit
from .casadm_params import *
from .casctl import stop as casctl_stop
from .cli import *


def help(shortcut: bool = False):
    return TestRun.executor.run(help_cmd(shortcut))


def start_cache(cache_dev: Device, cache_mode: CacheMode = None,
                cache_line_size: CacheLineSize = None, cache_id: int = None,
                force: bool = False, load: bool = False, shortcut: bool = False):
    _cache_line_size = None if cache_line_size is None else str(
        int(cache_line_size.value.get_value(Unit.KibiByte)))
    _cache_id = None if cache_id is None else str(cache_id)
    _cache_mode = None if cache_mode is None else cache_mode.name.lower()
    output = TestRun.executor.run(start_cmd(
        cache_dev=cache_dev.system_path, cache_mode=_cache_mode, cache_line_size=_cache_line_size,
        cache_id=_cache_id, force=force, load=load, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to start cache.", output)

    return Cache(cache_dev)


def stop_cache(cache_id: int, no_data_flush: bool = False, shortcut: bool = False):
    output = TestRun.executor.run(
        stop_cmd(cache_id=str(cache_id), no_data_flush=no_data_flush, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to stop cache.", output)
    return output


def add_core(cache: Cache, core_dev: Device, core_id: int = None, shortcut: bool = False):
    _core_id = None if core_id is None else str(core_id)
    output = TestRun.executor.run(
        add_core_cmd(cache_id=str(cache.cache_id), core_dev=core_dev.system_path,
                     core_id=_core_id, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to add core.", output)
    core = Core(core_dev.system_path, cache.cache_id)
    return core


def remove_core(cache_id: int, core_id: int, force: bool = False, shortcut: bool = False):
    output = TestRun.executor.run(
        remove_core_cmd(cache_id=str(cache_id), core_id=str(core_id),
                        force=force, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to remove core.", output)


def remove_detached(core_device: Device, shortcut: bool = False):
    output = TestRun.executor.run(
        remove_detached_cmd(core_device=core_device.system_path, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to remove detached core.", output)
    return output


def try_add(core_device: Device, cache_id: int, core_id: int = None):
    output = TestRun.executor.run(script_try_add_cmd(str(cache_id), core_device.system_path,
                                                     str(core_id) if core_id is not None else None))
    if output.exit_code != 0:
        raise CmdException("Failed to execute try add script command.", output)
    return Core(core_device.system_path, cache_id)


def purge_cache(cache_id: int):
    output = TestRun.executor.run(script_purge_cache_cmd(str(cache_id)))
    if output.exit_code != 0:
        raise CmdException("Purge cache failed.", output)
    return output


def purge_core(cache_id: int, core_id: int):
    output = TestRun.executor.run(script_purge_core_cmd(str(cache_id), str(core_id)))
    if output.exit_code != 0:
        raise CmdException("Purge core failed.", output)
    return output


def detach_core(cache_id: int, core_id: int):
    output = TestRun.executor.run(script_detach_core_cmd(str(cache_id), str(core_id)))
    if output.exit_code != 0:
        raise CmdException("Failed to execute detach core script command.", output)
    return output


def reset_counters(cache_id: int, core_id: int = None, shortcut: bool = False):
    _core_id = None if core_id is None else str(core_id)
    output = TestRun.executor.run(
        reset_counters_cmd(cache_id=str(cache_id), core_id=_core_id, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to reset counters.", output)
    return output


def flush(cache_id: int, core_id: int = None, shortcut: bool = False):
    if core_id is None:
        command = flush_cache_cmd(cache_id=str(cache_id), shortcut=shortcut)
    else:
        command = flush_core_cmd(cache_id=str(cache_id), core_id=str(core_id), shortcut=shortcut)
    output = TestRun.executor.run(command)
    if output.exit_code != 0:
        raise CmdException("Flushing failed.", output)
    return output


def load_cache(device: Device, shortcut: bool = False):
    output = TestRun.executor.run(
        load_cmd(cache_dev=device.system_path, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to load cache.", output)

    return Cache(device)


def list_caches(output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        list_cmd(output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to list caches.", output)
    return output


def print_version(output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        version_cmd(output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to print version.", output)
    return output


def zero_metadata(cache_dev: Device, shortcut: bool = False):
    output = TestRun.executor.run(
        zero_metadata_cmd(cache_dev=cache_dev.system_path, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to wipe metadata.", output)
    return output


def stop_all_caches():
    if "No caches running" in list_caches().stdout:
        return
    TestRun.LOGGER.info("Stop all caches")
    casctl_stop()
    output = list_caches()
    if "No caches running" not in output.stdout:
        raise CmdException("Error while stopping caches.", output)


def remove_all_detached_cores():
    from api.cas import casadm_parser
    devices = casadm_parser.get_cas_devices_dict()
    for dev in devices["core_pool"]:
        TestRun.executor.run(remove_detached_cmd(dev["device"]))


def print_statistics(cache_id: int, core_id: int = None, per_io_class: bool = False,
                     io_class_id: int = None, filter: List[StatsFilter] = None,
                     output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    _core_id = None if core_id is None else str(core_id)
    _io_class_id = None if io_class_id is None else str(io_class_id)
    if filter is None:
        _filter = filter
    else:
        names = (x.name for x in filter)
        _filter = ",".join(names)
    output = TestRun.executor.run(
        print_statistics_cmd(
            cache_id=str(cache_id), core_id=_core_id,
            per_io_class=per_io_class, io_class_id=_io_class_id,
            filter=_filter, output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Printing statistics failed.", output)
    return output


def set_cache_mode(cache_mode: CacheMode, cache_id: int,
                   flush=None, shortcut: bool = False):
    flush_cache = None
    if flush is True:
        flush_cache = "yes"
    elif flush is False:
        flush_cache = "no"

    output = TestRun.executor.run(
        set_cache_mode_cmd(cache_mode=cache_mode.name.lower(), cache_id=str(cache_id),
                           flush_cache=flush_cache, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Set cache mode command failed.", output)
    return output


def load_io_classes(cache_id: int, file: str, shortcut: bool = False):
    output = TestRun.executor.run(
        load_io_classes_cmd(cache_id=str(cache_id), file=file, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Load IO class command failed.", output)
    return output


def list_io_classes(cache_id: int, output_format: OutputFormat, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        list_io_classes_cmd(cache_id=str(cache_id),
                            output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("List IO class command failed.", output)
    return output


def get_param_cutoff(cache_id: int, core_id: int,
                     output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        get_param_cutoff_cmd(cache_id=str(cache_id), core_id=str(core_id),
                             output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Getting sequential cutoff params failed.", output)
    return output


def get_param_cleaning(cache_id: int, output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        get_param_cleaning_cmd(cache_id=str(cache_id), output_format=_output_format,
                               shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Getting cleaning policy params failed.", output)
    return output


def get_param_cleaning_alru(cache_id: int, output_format: OutputFormat = None,
                            shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        get_param_cleaning_alru_cmd(cache_id=str(cache_id), output_format=_output_format,
                                    shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Getting alru cleaning policy params failed.", output)
    return output


def get_param_cleaning_acp(cache_id: int, output_format: OutputFormat = None,
                           shortcut: bool = False):
    _output_format = None if output_format is None else output_format.name
    output = TestRun.executor.run(
        get_param_cleaning_acp_cmd(cache_id=str(cache_id), output_format=_output_format,
                                   shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Getting acp cleaning policy params failed.", output)
    return output


def set_param_cutoff(cache_id: int, core_id: int = None, threshold: Size = None,
                     policy: SeqCutOffPolicy = None):
    _core_id = None if core_id is None else str(core_id)
    _threshold = None if threshold is None else str(int(threshold.get_value(Unit.KibiByte)))
    _policy = None if policy is None else policy.name
    command = set_param_cutoff_cmd(
        cache_id=str(cache_id), core_id=_core_id, threshold=_threshold, policy=_policy)
    output = TestRun.executor.run(command)
    if output.exit_code != 0:
        raise CmdException("Error while setting sequential cut-off params.", output)
    return output


def set_param_cleaning(cache_id: int, policy: CleaningPolicy):
    output = TestRun.executor.run(
        set_param_cleaning_cmd(cache_id=str(cache_id), policy=policy.name))
    if output.exit_code != 0:
        raise CmdException("Error while setting cleaning policy.", output)
    return output


def set_param_cleaning_alru(cache_id: int, wake_up: int = None, staleness_time: int = None,
                            flush_max_buffers: int = None, activity_threshold: int = None):
    output = TestRun.executor.run(
        set_param_cleaning_alru_cmd(
            cache_id=cache_id,
            wake_up=wake_up,
            staleness_time=staleness_time,
            flush_max_buffers=flush_max_buffers,
            activity_threshold=activity_threshold))
    if output.exit_code != 0:
        raise CmdException("Error while setting alru cleaning policy parameters.", output)
    return output


def set_param_cleaning_acp(cache_id: int, wake_up: int = None, flush_max_buffers: int = None):
    output = TestRun.executor.run(
        set_param_cleaning_acp_cmd(
            cache_id=str(cache_id),
            wake_up=str(wake_up) if wake_up is not None else None,
            flush_max_buffers=str(flush_max_buffers) if flush_max_buffers else None))
    if output.exit_code != 0:
        raise CmdException("Error while setting acp cleaning policy parameters.", output)
    return output
