#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from typing import List

from api.cas.cache import Cache
from api.cas.cache_config import (
    CacheLineSize,
    CacheMode,
    SeqCutOffPolicy,
    CleaningPolicy,
    KernelParameters,
    PromotionPolicy,
)
from api.cas.casadm_params import OutputFormat, StatsFilter
from api.cas.cli import *
from api.cas.core import Core
from core.test_run import TestRun
from storage_devices.device import Device
from test_tools.os_tools import reload_kernel_module
from connection.utils.output import CmdException, Output
from type_def.size import Size, Unit


# casadm commands


def start_cache(
    cache_dev: Device,
    cache_mode: CacheMode = None,
    cache_line_size: CacheLineSize = None,
    cache_id: int = None,
    force: bool = False,
    load: bool = False,
    shortcut: bool = False,
    kernel_params: KernelParameters = KernelParameters(),
) -> Cache:
    if kernel_params != KernelParameters.read_current_settings():
        reload_kernel_module("cas_cache", kernel_params.get_parameter_dictionary())

    _cache_line_size = (
        str(int(cache_line_size.value.get_value(Unit.KibiByte)))
        if cache_line_size is not None
        else None
    )
    _cache_id = str(cache_id) if cache_id is not None else None
    _cache_mode = cache_mode.name.lower() if cache_mode else None

    output = TestRun.executor.run(
        start_cmd(
            cache_dev=cache_dev.path,
            cache_mode=_cache_mode,
            cache_line_size=_cache_line_size,
            cache_id=_cache_id,
            force=force,
            load=load,
            shortcut=shortcut,
        )
    )

    if output.exit_code != 0:
        raise CmdException("Failed to start cache.", output)

    if not _cache_id:
        from api.cas.casadm_parser import get_caches

        cache_list = get_caches()
        attached_cache_list = [cache for cache in cache_list if cache.cache_device is not None]
        # compare path of old and new caches, returning the only one created now.
        # This will be needed in case cache_id not present in cli command

        new_cache = next(
            cache for cache in attached_cache_list if cache.cache_device.path == cache_dev.path
        )
        _cache_id = new_cache.cache_id

    cache = Cache(cache_id=int(_cache_id), device=cache_dev, cache_line_size=cache_line_size)
    TestRun.dut.cache_list.append(cache)
    return cache


def load_cache(device: Device, shortcut: bool = False) -> Cache:
    from api.cas.casadm_parser import get_caches

    caches_before_load = get_caches()
    output = TestRun.executor.run(load_cmd(cache_dev=device.path, shortcut=shortcut))

    if output.exit_code != 0:
        raise CmdException("Failed to load cache.", output)

    caches_after_load = get_caches()
    new_cache = next(cache for cache in caches_after_load if cache.cache_id not in
                     [cache.cache_id for cache in caches_before_load])
    cache = Cache(cache_id=new_cache.cache_id, device=new_cache.cache_device)
    TestRun.dut.cache_list.append(cache)
    return cache


def attach_cache(
    cache_id: int, device: Device, force: bool = False, shortcut: bool = False
) -> Output:
    output = TestRun.executor.run(
        attach_cache_cmd(
            cache_dev=device.path, cache_id=str(cache_id), force=force, shortcut=shortcut
        )
    )

    if output.exit_code != 0:
        raise CmdException("Failed to attach cache.", output)

    attached_cache = next(cache for cache in TestRun.dut.cache_list if cache.cache_id == cache_id)
    attached_cache.cache_device = device

    return output


def detach_cache(cache_id: int, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(detach_cache_cmd(cache_id=str(cache_id), shortcut=shortcut))

    if output.exit_code != 0:
        raise CmdException("Failed to detach cache.", output)

    detached_cache = next(cache for cache in TestRun.dut.cache_list if cache.cache_id == cache_id)
    detached_cache.cache_device = None
    return output


def stop_cache(cache_id: int, no_data_flush: bool = False, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        stop_cmd(cache_id=str(cache_id), no_data_flush=no_data_flush, shortcut=shortcut)
    )

    if output.exit_code != 0:
        raise CmdException("Failed to stop cache.", output)

    TestRun.dut.cache_list = [
        cache for cache in TestRun.dut.cache_list if cache.cache_id != cache_id
    ]

    TestRun.dut.core_list = [core for core in TestRun.dut.core_list if core.cache_id != cache_id]

    return output


def set_param_cutoff(
    cache_id: int,
    core_id: int = None,
    threshold: Size = None,
    policy: SeqCutOffPolicy = None,
    promotion_count: int = None,
    shortcut: bool = False,
) -> Output:
    _core_id = str(core_id) if core_id is not None else None
    _threshold = str(int(threshold.get_value(Unit.KibiByte))) if threshold else None
    _policy = policy.name if policy else None
    _promotion_count = str(promotion_count) if promotion_count is not None else None
    command = set_param_cutoff_cmd(
        cache_id=str(cache_id),
        core_id=_core_id,
        threshold=_threshold,
        policy=_policy,
        promotion_count=_promotion_count,
        shortcut=shortcut,
    )
    output = TestRun.executor.run(command)
    if output.exit_code != 0:
        raise CmdException("Error while setting sequential cut-off params.", output)
    return output


def set_param_cleaning(cache_id: int, policy: CleaningPolicy, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        set_param_cleaning_cmd(cache_id=str(cache_id), policy=policy.name, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Error while setting cleaning policy.", output)
    return output


def set_param_cleaning_alru(
    cache_id: int,
    wake_up: int = None,
    staleness_time: int = None,
    flush_max_buffers: int = None,
    activity_threshold: int = None,
    shortcut: bool = False,
) -> Output:
    _wake_up = str(wake_up) if wake_up is not None else None
    _staleness_time = str(staleness_time) if staleness_time is not None else None
    _flush_max_buffers = str(flush_max_buffers) if flush_max_buffers is not None else None
    _activity_threshold = str(activity_threshold) if activity_threshold is not None else None
    output = TestRun.executor.run(
        set_param_cleaning_alru_cmd(
            cache_id=str(cache_id),
            wake_up=_wake_up,
            staleness_time=_staleness_time,
            flush_max_buffers=_flush_max_buffers,
            activity_threshold=_activity_threshold,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Error while setting alru cleaning policy parameters.", output)
    return output


def set_param_cleaning_acp(
    cache_id: int, wake_up: int = None, flush_max_buffers: int = None, shortcut: bool = False
) -> Output:
    _wake_up = str(wake_up) if wake_up is not None else None
    _flush_max_buffers = str(flush_max_buffers) if flush_max_buffers is not None else None
    output = TestRun.executor.run(
        set_param_cleaning_acp_cmd(
            cache_id=str(cache_id),
            wake_up=_wake_up,
            flush_max_buffers=_flush_max_buffers,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Error while setting acp cleaning policy parameters.", output)
    return output


def set_param_promotion(cache_id: int, policy: PromotionPolicy, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        set_param_promotion_cmd(
            cache_id=str(cache_id),
            policy=policy.name,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Error while setting promotion policy.", output)
    return output


def set_param_promotion_nhit(
    cache_id: int, threshold: int = None, trigger: int = None, shortcut: bool = False
) -> Output:
    _threshold = str(threshold) if threshold is not None else None
    _trigger = str(trigger) if trigger is not None else None
    output = TestRun.executor.run(
        set_param_promotion_nhit_cmd(
            cache_id=str(cache_id),
            threshold=_threshold,
            trigger=_trigger,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Error while setting promotion policy.", output)
    return output


def get_param_cutoff(
    cache_id: int, core_id: int, output_format: OutputFormat = None, shortcut: bool = False
) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_cutoff_cmd(
            cache_id=str(cache_id),
            core_id=str(core_id),
            output_format=_output_format,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting sequential cutoff params failed.", output)
    return output


def get_param_cleaning(cache_id: int, output_format: OutputFormat = None, shortcut: bool = False):
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_cleaning_cmd(
            cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting cleaning policy failed.", output)
    return output


def get_param_cleaning_alru(
    cache_id: int, output_format: OutputFormat = None, shortcut: bool = False
):
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_cleaning_alru_cmd(
            cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting alru cleaning policy params failed.", output)
    return output


def get_param_cleaning_acp(
    cache_id: int, output_format: OutputFormat = None, shortcut: bool = False
):
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_cleaning_acp_cmd(
            cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting acp cleaning policy params failed.", output)
    return output


def get_param_promotion(
    cache_id: int, output_format: OutputFormat = None, shortcut: bool = False
) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_promotion_cmd(
            cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting promotion policy failed.", output)
    return output


def get_param_promotion_nhit(
    cache_id: int, output_format: OutputFormat = None, shortcut: bool = False
) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        get_param_promotion_nhit_cmd(
            cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Getting promotion policy nhit params failed.", output)
    return output


def set_cache_mode(
    cache_mode: CacheMode, cache_id: int, flush: bool = None, shortcut: bool = False
) -> Output:
    flush_cache = None
    if flush is not None:
        flush_cache = "yes" if flush else "no"
    output = TestRun.executor.run(
        set_cache_mode_cmd(
            cache_mode=cache_mode.name.lower(),
            cache_id=str(cache_id),
            flush_cache=flush_cache,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Set cache mode command failed.", output)
    return output


def add_core(cache: Cache, core_dev: Device, core_id: int = None, shortcut: bool = False) -> Core:
    _core_id = str(core_id) if core_id is not None else None
    output = TestRun.executor.run(
        add_core_cmd(
            cache_id=str(cache.cache_id),
            core_dev=core_dev.path,
            core_id=_core_id,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Failed to add core.", output)

    core = Core(core_dev.path, cache.cache_id)
    TestRun.dut.core_list.append(core)

    return core


def remove_core(cache_id: int, core_id: int, force: bool = False, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        remove_core_cmd(
            cache_id=str(cache_id), core_id=str(core_id), force=force, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Failed to remove core.", output)

    TestRun.dut.core_list = [
        core
        for core in TestRun.dut.core_list
        if core.cache_id != cache_id or core.core_id != core_id
    ]
    return output


def remove_inactive(
    cache_id: int, core_id: int, force: bool = False, shortcut: bool = False
) -> Output:
    output = TestRun.executor.run(
        remove_inactive_cmd(
            cache_id=str(cache_id), core_id=str(core_id), force=force, shortcut=shortcut
        )
    )
    if output.exit_code != 0:
        raise CmdException("Failed to remove inactive core.", output)
    return output


def remove_detached(core_device: Device, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        remove_detached_cmd(core_device=core_device.path, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Failed to remove detached core.", output)
    return output


def list_caches(
    output_format: OutputFormat = None, by_id_path: bool = True, shortcut: bool = False
) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        list_caches_cmd(output_format=_output_format, by_id_path=by_id_path, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Failed to list caches.", output)
    return output


def print_statistics(
    cache_id: int,
    core_id: int = None,
    io_class_id: int = None,
    filter: List[StatsFilter] = None,
    output_format: OutputFormat = None,
    by_id_path: bool = True,
    io_class: bool = False,
    shortcut: bool = False,
) -> Output:
    _output_format = output_format.name if output_format else None
    _io_class_id = str(io_class_id) if io_class_id is not None else "" if io_class else None
    _core_id = str(core_id) if core_id is not None else None
    if filter is None:
        _filter = filter
    else:
        names = (x.name for x in filter)
        _filter = ",".join(names)
    output = TestRun.executor.run(
        print_statistics_cmd(
            cache_id=str(cache_id),
            core_id=_core_id,
            io_class_id=_io_class_id,
            filter=_filter,
            output_format=_output_format,
            by_id_path=by_id_path,
            shortcut=shortcut,
        )
    )
    if output.exit_code != 0:
        raise CmdException("Printing statistics failed.", output)
    return output


def reset_counters(cache_id: int, core_id: int = None, shortcut: bool = False) -> Output:
    _core_id = str(core_id) if core_id is not None else None
    output = TestRun.executor.run(
        reset_counters_cmd(cache_id=str(cache_id), core_id=_core_id, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Failed to reset counters.", output)
    return output


def flush_cache(cache_id: int, shortcut: bool = False) -> Output:
    command = flush_cache_cmd(cache_id=str(cache_id), shortcut=shortcut)
    output = TestRun.executor.run(command)
    if output.exit_code != 0:
        raise CmdException("Flushing cache failed.", output)
    return output


def flush_core(cache_id: int, core_id: int, shortcut: bool = False) -> Output:
    command = flush_core_cmd(cache_id=str(cache_id), core_id=str(core_id), shortcut=shortcut)
    output = TestRun.executor.run(command)
    if output.exit_code != 0:
        raise CmdException("Flushing core failed.", output)
    return output


def load_io_classes(cache_id: int, file: str, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        load_io_classes_cmd(cache_id=str(cache_id), file=file, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Load IO class command failed.", output)
    return output


def list_io_classes(cache_id: int, output_format: OutputFormat, shortcut: bool = False) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(
        list_io_classes_cmd(cache_id=str(cache_id), output_format=_output_format, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("List IO class command failed.", output)
    return output


def print_version(output_format: OutputFormat = None, shortcut: bool = False) -> Output:
    _output_format = output_format.name if output_format else None
    output = TestRun.executor.run(version_cmd(output_format=_output_format, shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to print version.", output)
    return output


def help(shortcut: bool = False) -> Output:
    return TestRun.executor.run(help_cmd(shortcut))


def standby_init(
    cache_dev: Device,
    cache_id: int,
    cache_line_size: CacheLineSize,
    force: bool = False,
    shortcut: bool = False,
    kernel_params: KernelParameters = KernelParameters(),
) -> Cache:
    if kernel_params != KernelParameters.read_current_settings():
        reload_kernel_module("cas_cache", kernel_params.get_parameter_dictionary())
    _cache_line_size = str(int(cache_line_size.value.get_value(Unit.KibiByte)))

    output = TestRun.executor.run(
        standby_init_cmd(
            cache_dev=cache_dev.path,
            cache_id=str(cache_id),
            cache_line_size=_cache_line_size,
            force=force,
            shortcut=shortcut,
        )
    )

    if output.exit_code != 0:
        raise CmdException("Failed to init standby cache.", output)
    return Cache(cache_id=cache_id, device=cache_dev)


def standby_load(cache_dev: Device, shortcut: bool = False) -> Cache:
    from api.cas.casadm_parser import get_caches

    caches_before_load = get_caches()
    output = TestRun.executor.run(standby_load_cmd(cache_dev=cache_dev.path, shortcut=shortcut))

    if output.exit_code != 0:
        raise CmdException("Failed to load cache.", output)
    caches_after_load = get_caches()
    # compare ids of old and new caches, returning the only one created now
    new_cache = next(
        cache
        for cache in caches_after_load
        if cache.cache_id not in [cache.cache_id for cache in caches_before_load]
    )
    cache = Cache(cache_id=new_cache.cache_id, device=new_cache.cache_device)
    TestRun.dut.cache_list.append(cache)

    return cache


def standby_detach_cache(cache_id: int, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(standby_detach_cmd(cache_id=str(cache_id), shortcut=shortcut))
    if output.exit_code != 0:
        raise CmdException("Failed to detach standby cache.", output)

    detached_cache = next(cache for cache in TestRun.dut.cache_list if cache.cache_id == cache_id)
    detached_cache.cache_device = None

    return output


def standby_activate_cache(cache_dev: Device, cache_id: int, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        standby_activate_cmd(cache_dev=cache_dev.path, cache_id=str(cache_id), shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Failed to activate standby cache.", output)

    activated_cache = next(cache for cache in TestRun.dut.cache_list if cache.cache_id == cache_id)
    activated_cache.cache_device = cache_dev

    return output


def zero_metadata(cache_dev: Device, force: bool = False, shortcut: bool = False) -> Output:
    output = TestRun.executor.run(
        zero_metadata_cmd(cache_dev=cache_dev.path, force=force, shortcut=shortcut)
    )
    if output.exit_code != 0:
        raise CmdException("Failed to wipe metadata.", output)
    return output


# script command


def try_add(core_device: Device, cache_id: int, core_id: int) -> Core:
    output = TestRun.executor.run(script_try_add_cmd(str(cache_id), core_device.path, str(core_id)))
    if output.exit_code != 0:
        raise CmdException("Failed to execute try add script command.", output)
    return Core(core_device.path, cache_id)


def purge_cache(cache_id: int) -> Output:
    output = TestRun.executor.run(script_purge_cache_cmd(str(cache_id)))
    if output.exit_code != 0:
        raise CmdException("Purge cache failed.", output)
    return output


def purge_core(cache_id: int, core_id: int) -> Output:
    output = TestRun.executor.run(script_purge_core_cmd(str(cache_id), str(core_id)))
    if output.exit_code != 0:
        raise CmdException("Purge core failed.", output)
    return output


def detach_core(cache_id: int, core_id: int) -> Output:
    output = TestRun.executor.run(script_detach_core_cmd(str(cache_id), str(core_id)))
    if output.exit_code != 0:
        raise CmdException("Failed to execute detach core script command.", output)
    return output


def remove_core_with_script_command(cache_id: int, core_id: int, no_flush: bool = False) -> Output:
    output = TestRun.executor.run(script_remove_core_cmd(str(cache_id), str(core_id), no_flush))
    if output.exit_code != 0:
        raise CmdException("Failed to execute remove core script command.", output)
    return output


# casadm custom commands


def stop_all_caches() -> None:
    from api.cas.casadm_parser import get_caches

    caches = get_caches()
    if not caches:
        return
    # Running "cache stop" on the reversed list to resolve the multilevel cache stop problem
    for cache in reversed(caches):
        stop_cache(cache_id=cache.cache_id, no_data_flush=True)


def remove_all_detached_cores() -> None:
    from api.cas.casadm_parser import get_cas_devices_dict

    devices = get_cas_devices_dict()
    for dev in devices["core_pool"].values():
        TestRun.executor.run(remove_detached_cmd(dev["device_path"]))
