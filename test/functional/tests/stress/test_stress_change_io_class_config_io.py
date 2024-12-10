#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import random
import threading
import pytest

from datetime import timedelta
from time import sleep
from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.ioclass_config import IoClass
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine
from connection.utils.asynchronous import start_async_func
from types.size import Size, Unit
from tests.io_class.io_class_common import generate_and_load_random_io_class_config


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_io_class_change_config_during_io_raw():
    """
    title: Set up IO class configuration from file during IO - stress.
    description: |
        Check Open CAS ability to change IO class configuration during running IO
        on small cache and core devices.
    pass_criteria:
        - No system crash
        - IO class configuration changes successfully
        - No IO errors
    """
    cores_per_cache = 4

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(150, Unit.MebiByte)])
        core_device.create_partitions([Size(256, Unit.MebiByte)] * cores_per_cache)

        cache_device = cache_device.partitions[0]

    with TestRun.step("Start cache in Write-Back mode and add core devices."):
        cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(part) for part in core_device.partitions]

    with TestRun.step("Create IO class configuration file for 33 IO classes with random allocation "
                      "and priority value."):
        generate_and_load_random_io_class_config(cache)

    with TestRun.step("Run IO for all CAS devices."):
        fio_task = start_async_func(run_io, cores, True)

    with TestRun.step("In two-second time interval change IO class configuration "
                      "(using random values in allowed range) and cache mode "
                      "(between all supported). Check if Open CAS configuration has changed."):
        change_mode_thread = threading.Thread(target=change_cache_mode, args=[cache, fio_task])
        change_io_class_thread = threading.Thread(target=change_io_class_config,
                                                  args=[cache, fio_task])
        change_mode_thread.start()
        sleep(1)
        change_io_class_thread.start()

        while change_io_class_thread.is_alive() or change_mode_thread.is_alive():
            sleep(10)

        fio_result = fio_task.result()
        if fio_result.exit_code != 0:
            TestRun.fail("Fio ended with an error!")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.asyncio
async def test_stress_io_class_change_config_during_io_fs():
    """
    title: Set up IO class configuration from file for filesystems during IO - stress.
    description: |
        Check Intel CAS ability to change IO class configuration for different filesystems
        during running IO on small cache and core devices.
    pass_criteria:
        - No system crash
        - IO class configuration changes successfully
        - No IO errors
    """
    cores_per_cache = len(list(Filesystem))

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(150, Unit.MebiByte)])
        core_device.create_partitions([Size(3, Unit.GibiByte)] * cores_per_cache)

        cache_device = cache_device.partitions[0]

    with TestRun.step("Start cache in Write-Back mode and add core devices."):
        cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(part) for part in core_device.partitions]

    with TestRun.step("Create IO class configuration file for 33 IO classes with random allocation "
                      "and priority value."):
        generate_and_load_random_io_class_config(cache)

    with TestRun.step("Create different filesystem on each CAS device."):
        for core, fs in zip(cores, Filesystem):
            core.create_filesystem(fs)
            core.mount(os.path.join("/mnt", fs.name))

    with TestRun.step("Run IO for all CAS devices."):
        fio_task = start_async_func(run_io, cores)

    with TestRun.step("In two-second time interval change IO class configuration "
                      "(using random values in allowed range) and cache mode "
                      "(between all supported). Check if Open CAS configuration has changed."):
        change_mode_thread = threading.Thread(target=change_cache_mode, args=[cache, fio_task])
        change_io_class_thread = threading.Thread(target=change_io_class_config,
                                                  args=[cache, fio_task])
        change_mode_thread.start()
        sleep(1)
        change_io_class_thread.start()

        while change_io_class_thread.is_alive() or change_mode_thread.is_alive():
            sleep(10)

        fio_result = fio_task.result()
        if fio_result.exit_code != 0:
            TestRun.fail("Fio ended with an error!")


def change_cache_mode(cache, fio_task):
    while fio_task.done() is False:
        sleep(2)
        current_cache_mode = cache.get_cache_mode()
        cache_modes = list(CacheMode)
        cache_modes.remove(current_cache_mode)
        new_cache_mode = random.choice(cache_modes)
        cache.set_cache_mode(new_cache_mode, False)


def change_io_class_config(cache, fio_task):
    while fio_task.done() is False:
        sleep(2)
        generated_io_classes = generate_and_load_random_io_class_config(cache)
        loaded_io_classes = cache.list_io_classes()
        if not IoClass.compare_ioclass_lists(generated_io_classes, loaded_io_classes):
            TestRun.LOGGER.error("IO classes not changed correctly.")
            generated_io_classes = '\n'.join(str(i) for i in generated_io_classes)
            TestRun.LOGGER.error(f"Generated IO classes:\n{generated_io_classes}")
            loaded_io_classes = '\n'.join(str(i) for i in loaded_io_classes)
            TestRun.LOGGER.error(f"Loaded IO classes:\n{loaded_io_classes}")


def run_io(cores, direct=False):
    fio = Fio().create_command() \
        .io_engine(IoEngine.libaio) \
        .time_based() \
        .run_time(timedelta(hours=2)) \
        .do_verify() \
        .sync() \
        .block_size(Size(1, Unit.Blocks4096)) \
        .file_size(Size(2, Unit.GibiByte))
    if direct:
        fio.direct()
        for core in cores:
            fio.add_job().target(core.path)
    else:
        for core in cores:
            fio.add_job().target(os.path.join(core.mount_point, "file"))

    return fio.fio.run()
