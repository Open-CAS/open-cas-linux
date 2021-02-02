#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
from time import sleep

from api.cas.casadm import start_cache
from api.cas.casadm_parser import get_caches
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.cas_ioctl.cas_requests import StartCacheRequest
from test_tools.cas_ioctl.cas_structs import CacheMode, CacheLineSize, InitCache
from test_tools.cas_ioctl.ioctl import cas_ioctl
from test_utils.size import Size, Unit
from tests.ioctl import common_utils

cache_id = 3


@pytest.mark.parametrizex("force", [0, 1])
@pytest.mark.parametrizex("load", InitCache)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_ioctl_start(cache_mode, cache_line_size, load, force):
    """
        title: Start the cache without casadm.
        description: |
          Test of the ability to start the cache with IOCTL request bypassing native
          OpenCAS manager - casadm.
        pass_criteria:
          - Cache started successfully without any errors.
          - When 'force' and 'load' flags are used cache is not started.
    """
    with TestRun.step("Prepare cache device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GiB)])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Create IOCTL request for cache start."):
        start_config = StartCacheRequest(
            cache_path_name=cache_part.path, caching_mode=cache_mode, cache_id=cache_id,
            init_cache=load, force=force, line_size=cache_line_size
        )

    if load.value:
        with TestRun.step("Start and stop cache before loading."):
            cache = start_cache(cache_part, cache_id=cache_id, force=True)
            cache.stop()

    with TestRun.step("Start cache with IOCTL request bypassing casadm."):
        cas_ioctl(start_config)

    with TestRun.step(
            f"Check if cache is {'running' if not (load.value and force) else 'not running'}."
    ):
        if not (load.value and force):
            if len(get_caches()) != 1:
                TestRun.fail("Cache is missing!")
        else:
            if len(get_caches()) != 0:
                TestRun.fail("Cache should not be loaded!")


@pytest.mark.parametrizex("force", [0, 1])
@pytest.mark.parametrizex("load", InitCache)
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_ioctl_start_interrupt(cache_mode, cache_line_size, load, force):
    """
        title: Interrupt cache start without casadm.
        description: |
          Negative test of the ability to interrupt the cache start with IOCTL request sent
          outside native OpenCAS manager - casadm.
        pass_criteria:
          - Cache is not started.
    """
    with TestRun.step("Prepare cache device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(128, Unit.GiB)])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Create IOCTL request for cache start."):
        start_config = StartCacheRequest(
            cache_path_name=cache_part.path, caching_mode=cache_mode, cache_id=cache_id,
            init_cache=load, force=force, line_size=cache_line_size
        )

    if load.value:
        with TestRun.step("Start and stop cache before loading."):
            cache = start_cache(cache_part, cache_id=cache_id, force=True)
            cache.stop()

    with TestRun.step("Clear dmesg."):
        common_utils.clear_dmesg()

    with TestRun.step("Interrupt starting cache with IOCTL request bypassing casadm."):
        cas_ioctl(start_config, True)
        sleep(8)    # wait for rollback after interruption

    with TestRun.step(f"Check if cache is not running."):
        if len(get_caches()) > 0:
            TestRun.fail('Start process finished. Interruption failed.')
        else:
            TestRun.LOGGER.info('Start process is dead as expected.')

    with TestRun.step("Check dmesg for interruption log."):
        common_utils.check_dmesg(common_utils.load_and_force if (load.value and force)
                                 else common_utils.interrupt_start)
