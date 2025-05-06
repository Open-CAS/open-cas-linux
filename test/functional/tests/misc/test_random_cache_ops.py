#
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import (
    CacheMode,
    SeqCutOffParameters,
    SeqCutOffPolicy,
    CleaningPolicy,
    FlushParametersAlru,
    PromotionParametersNhit,
    PromotionPolicy,
    FlushParametersAcp,
)
from api.cas.casadm_parser import get_caches, get_inactive_cores, get_detached_cores
from api.cas.cli_messages import (
    start_cache_with_existing_metadata,
    check_stderr_msg,
    no_cas_metadata,
    start_cache_with_existing_id,
    attach_cache_with_existing_metadata,
)
from connection.utils.output import CmdException
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from datetime import datetime, timedelta

from type_def.size import Size, Unit
from type_def.time import Time

io_engine_list = [
    IoEngine.sync,
    IoEngine.libaio,
    IoEngine.psync,
    IoEngine.pvsync,
    IoEngine.posixaio,
    IoEngine.mmap,
]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_random_operations():
    """
    title: Stress test for allowed operations.
    description: |
        Test running all allowed operation multiple times in random order.
    pass_criteria:
      - No system crash.
    """
    test_runtime = timedelta(minutes=60)

    with TestRun.step("Prepare disks"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(1, Unit.GibiByte)] * 5)
        core_dev.create_partitions([Size(2, Unit.GibiByte)] * 10)

    with TestRun.step("Start cache and add core"):
        main_cache = casadm.start_cache(cache_dev=cache_dev.partitions[0], force=True)
        main_cache.add_core(core_dev=core_dev.partitions[0])

    with TestRun.step("Run random operations"):
        used_cache_devices = [cache_dev.partitions[0]]
        available_cache_devices = cache_dev.partitions[1:]
        used_core_devices = [core_dev.partitions[0]]
        available_core_devices = core_dev.partitions[1:]
        operation_list = [
            start_cache,
            attach_cache,
            detach_cache,
            stop_cache,
            set_param,
            set_cache_mode,
            add_core,
            remove_core,
            remove_inactive,
            reset_counters,
            flush_cache,
            zero_metadata,
            run_fio,
        ]

        # set runtime of test
        test_start_time = datetime.now()
        step_name_list = []
        counter = 0

        try:
            while datetime.now() < test_start_time + test_runtime:
                counter += 1
                step = random.choice(operation_list)
                step_name = step(
                    available_cache_devices,
                    used_cache_devices,
                    available_core_devices,
                    used_core_devices,
                )
                if step_name:
                    step_name_list.append(step_name)
        except CmdException:
            step_name_list.append(step.__name__)
            step_list = "\n".join(step_name_list)
            TestRun.LOGGER.info(f"Counter: {counter}")
            TestRun.LOGGER.error(f"Steps to reproduce\n{step_list}")


def start_cache(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    if not available_cache_devices:
        return None

    device_to_start_cache = random.choice(available_cache_devices)
    cache_mode = random.choice(list(CacheMode))

    try:
        casadm.start_cache(cache_dev=device_to_start_cache, cache_mode=cache_mode)
        used_cache_devices.append(device_to_start_cache)
        available_cache_devices.remove(device_to_start_cache)
        return f"Started cache on {device_to_start_cache.path}"
    except CmdException as output:
        if check_stderr_msg(output.output, start_cache_with_existing_metadata):
            if random.choice([True, False]):
                try:
                    loaded_cache = casadm.load_cache(device=device_to_start_cache)
                    active_cores = loaded_cache.get_cores()

                    used_cache_devices.append(device_to_start_cache)
                    available_cache_devices.remove(device_to_start_cache)

                    used_core_devices.extend(
                        [
                            core
                            for cache_core in active_cores
                            for core in available_core_devices
                            if core.path == cache_core.core_device.path
                        ]
                    )

                    available_core_devices[:] = [
                        core
                        for core in available_core_devices
                        if core.path not in [device.core_device.path for device in active_cores]
                    ]

                    return f"Loaded cache using {device_to_start_cache.path} device"

                except CmdException as output:
                    if check_stderr_msg(output.output, start_cache_with_existing_id):
                        return None

            else:
                casadm.start_cache(
                    cache_dev=device_to_start_cache, cache_mode=cache_mode, force=True
                )
                used_cache_devices.append(device_to_start_cache)
                available_cache_devices.remove(device_to_start_cache)
                return f"Started cache with force flag {device_to_start_cache.path}"


def attach_cache(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    cache_list = get_caches()

    if not cache_list:
        return None

    detached_cache_list = [cache for cache in cache_list if cache.cache_device is None]

    if not detached_cache_list:
        return None

    cache_to_attach = random.choice(detached_cache_list)

    if not available_cache_devices:
        return None

    random_available_cache_device = random.choice(available_cache_devices)
    try:
        cache_to_attach.attach(random_available_cache_device)
    except CmdException as output:
        if check_stderr_msg(output.output, attach_cache_with_existing_metadata):
            cache_to_attach.attach(random_available_cache_device, force=True)

    used_cache_devices.append(random_available_cache_device)

    available_cache_devices.remove(random_available_cache_device)
    return f"Attached cache device to cache {cache_to_attach.cache_id}"


def detach_cache(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    cache_list = get_caches()

    if not cache_list:
        return None

    attached_cache_list = [cache for cache in cache_list if cache.cache_device is not None]

    if not attached_cache_list:
        return None

    cache_to_detach = random.choice(attached_cache_list)

    for device in used_cache_devices:
        if device.path == cache_to_detach.cache_device.path:
            cache_to_detach.detach()
            available_cache_devices.append(device)
            used_cache_devices.remove(device)
    return f"Detached cache device from cache {cache_to_detach.cache_id}"


def stop_cache(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    cache_list = get_caches()

    if not cache_list:
        return None

    cache_to_stop = random.choice(cache_list)
    inactive_cores = casadm_parser.get_inactive_cores(cache_id=cache_to_stop.cache_id)
    for core in inactive_cores:
        casadm_parser.get_inactive_cores(cache_id=cache_to_stop.cache_id)
        cache_to_stop.remove_inactive_core(core_id=core.core_id)

    detached_cores = casadm_parser.get_detached_cores(cache_id=cache_to_stop.cache_id)
    for core in detached_cores:
        casadm.remove_detached(core_device=core)

    active_cores = cache_to_stop.get_cores()
    available_core_devices.extend(
        [
            core
            for cache_core in active_cores
            for core in used_core_devices
            if core.path == cache_core.core_device.path
        ]
    )

    used_core_devices[:] = [
        core
        for core in used_core_devices
        if core.path not in [device.core_device.path for device in active_cores]
    ]

    if cache_to_stop.cache_device is None:
        cache_to_stop.stop()

    else:
        flush_operation = random.choice([True, False])
        if flush_operation:
            cache_to_stop.stop(no_data_flush=flush_operation)
            for device in used_cache_devices:
                if device.path == cache_to_stop.cache_device.path:
                    available_cache_devices.append(device)
                    used_cache_devices.remove(device)
            return f"Stopped cache {cache_to_stop.cache_id} with flush"
        else:
            cache_to_stop.stop(no_data_flush=flush_operation)
            for device in used_cache_devices:
                if device.path == cache_to_stop.cache_device.path:
                    available_cache_devices.append(device)
                    used_cache_devices.remove(device)
            return f"Stopped cache {cache_to_stop.cache_id} without flush"


def set_param(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    cache_list = get_caches()

    if not cache_list:
        return None

    attached_cache_list = [cache for cache in cache_list if cache.cache_device is not None]

    if not attached_cache_list:
        return None

    cache_to_set_param = random.choice(attached_cache_list)
    set_param_list = [
        cache_to_set_param.set_seq_cutoff_parameters,
        cache_to_set_param.set_cleaning_policy,
        cache_to_set_param.set_params_alru,
        cache_to_set_param.set_params_acp,
        cache_to_set_param.set_promotion_policy,
        cache_to_set_param.set_params_nhit,
    ]
    param_to_set = random.choice(set_param_list)
    match param_to_set:
        case cache_to_set_param.set_seq_cutoff_parameters:
            if random.choice([True, False]):
                random_threshold = Size(random.randint(1, 4194181))
                random_policy = random.choice(list(SeqCutOffPolicy))
                random_promotion_count = random.randint(1, 65535)
                random_seqcutoff_params = SeqCutOffParameters(
                    threshold=random_threshold,
                    policy=random_policy,
                    promotion_count=random_promotion_count,
                )
                cache_to_set_param.set_seq_cutoff_parameters(random_seqcutoff_params)
                return (
                    f"Changed seq-cutoff params on cache {cache_to_set_param.cache_id} to:\n"
                    f"Threshold: {str(random_threshold)}\n"
                    f"Policy: {str(random_policy)}\n"
                    f"Threshold: {str(random_threshold)}\n"
                )
            else:
                core_list = cache_to_set_param.get_cores()
                if not core_list:
                    return None
                random_core = random.choice(core_list)
                random_threshold = Size(random.randint(1, 4194181))
                random_policy = random.choice(list(SeqCutOffPolicy))
                random_promotion_count = random.randint(1, 65535)
                random_seqcutoff_params = SeqCutOffParameters(
                    threshold=random_threshold,
                    policy=random_policy,
                    promotion_count=random_promotion_count,
                )
                random_core.set_seq_cutoff_parameters(random_seqcutoff_params)
                return (
                    f"Changed seq-cutoff params on cache {cache_to_set_param.cache_id}-core "
                    f"{random_core.core_id} to:\n"
                    f"Threshold: {str(random_threshold)}\n"
                    f"Policy: {str(random_policy)}\n"
                    f"Promotion count: {str(random_promotion_count)}\n"
                )

        case cache_to_set_param.set_cleaning_policy:
            random_cleaning_policy = random.choice(list(CleaningPolicy))
            cache_to_set_param.set_cleaning_policy(cleaning_policy=random_cleaning_policy)
            return (
                f"Changed cleaning policy on cache {cache_to_set_param.cache_id} to:\n"
                f"Policy: {str(random_cleaning_policy)}\n"
            )

        case cache_to_set_param.set_promotion_policy:
            random_promotion_policy = random.choice(list(PromotionPolicy))
            cache_to_set_param.set_promotion_policy(policy=random_promotion_policy)
            return (
                f"Changed promotion policy on cache {cache_to_set_param.cache_id} to:\n"
                f"Promotion policy: {str(random_promotion_policy)}\n"
            )

        case cache_to_set_param.set_params_nhit:
            random_threshold = random.randint(2, 1000)
            random_trigger = random.randint(0, 100)
            random_promotion_nhit_params = PromotionParametersNhit(
                threshold=random_threshold,
                trigger=random_trigger,
            )
            cache_to_set_param.set_params_nhit(random_promotion_nhit_params)
            return (
                f"Changed promotion nhit params on cache {cache_to_set_param.cache_id} to:\n"
                f"Threshold: {str(random_threshold)}\n"
                f"Trigger: {str(random_trigger)}\n"
            )

        case cache_to_set_param.set_params_alru:
            random_wake_up_time = Time(seconds=random.randint(0, 3600))
            random_staleness_time = Time(seconds=random.randint(1, 3600))
            random_flush_max_buffers = random.randint(1, 10000)
            random_activity_threshold = Time(milliseconds=random.randint(0, 1000000))
            random_flush_parameters_alru = FlushParametersAlru(
                wake_up_time=random_wake_up_time,
                staleness_time=random_staleness_time,
                flush_max_buffers=random_flush_max_buffers,
                activity_threshold=random_activity_threshold,
            )
            cache_to_set_param.set_params_alru(random_flush_parameters_alru)
            return (
                f"Changing alru params on cache {cache_to_set_param.cache_id} to:\n"
                f"Wake up time: {str(random_wake_up_time)}\n"
                f"Staleness time: {str(random_staleness_time)}\n"
                f"Flush max buffers: {str(random_flush_max_buffers)}\n"
                f"Activity threshold time: {str(random_activity_threshold)}\n"
            )

        case cache_to_set_param.set_params_acp:
            random_wake_up_time = Time(milliseconds=random.randint(0, 10000))
            random_flush_max_buffers = random.randint(1, 10000)
            random_flush_parameters_acp = FlushParametersAcp(
                wake_up_time=random_wake_up_time,
                flush_max_buffers=random_flush_max_buffers,
            )
            cache_to_set_param.set_params_acp(acp_params=random_flush_parameters_acp)
            return (
                f"Changing acp params on cache {cache_to_set_param.cache_id} to:\n"
                f"Wake up time: {str(random_wake_up_time)}\n"
                f"Flush max buffers: {str(random_flush_max_buffers)}\n"
            )


def set_cache_mode(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    cache_list = get_caches()

    if not cache_list:
        return None

    attached_cache_list = [cache for cache in cache_list if cache.cache_device is not None]

    if not attached_cache_list:
        return None

    random_cache = random.choice(attached_cache_list)

    random_cachemode = random.choice(list(CacheMode))
    if random_cache.get_cache_mode() in [CacheMode.WB, CacheMode.WT]:
        random_cache.set_cache_mode(cache_mode=random_cachemode, flush=True)
        return f"Changed cached mode to {random_cachemode} on cache {random_cache.cache_id}"
    else:
        if random.choice([True, False]):
            random_cache.set_cache_mode(cache_mode=random_cachemode, flush=True)
            return (
                f"Changed cached mode to {random_cachemode} on cache {random_cache.cache_id} "
                f"with cache flush"
            )
        else:
            random_cache.set_cache_mode(cache_mode=random_cachemode, flush=False)
            return (
                f"Changed cached mode to {random_cachemode} on cache {random_cache.cache_id} "
                f"without cache flush"
            )


def add_core(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    if not available_core_devices:
        return None

    cache_list = get_caches()
    if not cache_list:
        return None

    cache_to_add_core = random.choice(cache_list)
    random_core_device = random.choice(available_core_devices)

    cache_to_add_core.add_core(core_dev=random_core_device)
    used_core_devices.append(random_core_device)
    available_core_devices.remove(random_core_device)

    return f"Device {random_core_device.path} added as core to cache {cache_to_add_core.cache_id}"


def remove_core(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    cache_list = get_caches()

    if not cache_list:
        return None

    if not used_core_devices:
        return None

    cache_list = [cache for cache in cache_list if cache.get_cores()]
    random_cache = random.choice(cache_list)
    core_list = random_cache.get_cores()
    random_core = random.choice(core_list)

    for core in used_core_devices:
        if core.path == random_core.path:
            random_cache.remove_core(core_id=random_core.core_id)
            available_core_devices.append(core)
            used_core_devices.remove(core)
    return f"Core {random_core.path} removed from cache {random_cache.cache_id}"


def remove_inactive(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    cache_list = get_caches()

    if not cache_list:
        return None

    if not available_core_devices:
        return None

    cache_list = [cache for cache in cache_list if cache.get_cores()]
    caches_with_inactive_cores = [
        cache for cache in cache_list if get_inactive_cores(cache_id=cache.cache_id)
    ]

    if not caches_with_inactive_cores:
        return None

    random_cache = random.choice(caches_with_inactive_cores)
    inactive_cores = get_inactive_cores(cache_id=random_cache.cache_id)

    random_inactive_core = random.choice(inactive_cores)
    random_cache.remove_inactive_core(random_inactive_core.core_id)

    return f"Removed inactive core from cache {random_cache.cache_id}"


def reset_counters(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    cache_list = get_caches()

    if not cache_list:
        return None
    random_cache = random.choice(cache_list)

    random_cache.reset_counters()
    return f"Reset stats on cache {random_cache.cache_id}"


def flush_cache(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    cache_list = get_caches()

    if not cache_list:
        return None

    attached_caches = [cache for cache in cache_list if cache.cache_device]

    if not attached_caches:
        return None

    random_cache = random.choice(attached_caches)

    inactive_cores = get_inactive_cores(cache_id=random_cache.cache_id)
    detached_cores = get_detached_cores(cache_id=random_cache.cache_id)
    if inactive_cores or detached_cores:
        return None

    random_cache.flush_cache()
    return f"Reset stats on cache {random_cache.cache_id}"


def zero_metadata(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
):
    if not available_cache_devices:
        return None

    random_device = random.choice(available_cache_devices)
    try:
        casadm.zero_metadata(cache_dev=random_device, force=True)
        return f"Removed metadata on device {random_device.path}"
    except CmdException as output:
        if check_stderr_msg(output.output, no_cas_metadata):
            return None


def run_fio(
    available_cache_devices: list,
    used_cache_devices: list,
    available_core_devices: list,
    used_core_devices: list,
) -> str | None:
    cache_list = get_caches()
    if not cache_list:
        return None

    random_cache = random.choice(cache_list)
    core_list = random_cache.get_cores()
    if not core_list:
        return None

    core_device_to_run_fio = random.choice(core_list)

    fio_command = (
        Fio()
        .create_command()
        .direct()
        .read_write(ReadWrite.randrw)
        .write_percentage(50)
        .io_engine(random.choice(io_engine_list))
        .run_time(timedelta(seconds=30))
        .block_size(Size(1, Unit.Blocks4096))
        .target(core_device_to_run_fio.path)
    )
    fio_command.run()
    return f"Fio run on {core_device_to_run_fio.path}"
