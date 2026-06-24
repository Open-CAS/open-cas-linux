#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from time import sleep

import pytest

from api.cas.casadm import start_cache
from api.cas.casadm_parser import get_caches
from api.cas.ioctl.cas_requests import StopCacheRequest
from api.cas.ioctl.ioctl import cas_ioctl
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_utils.size import Size, Unit
from tests.ioctl import common_utils

cache_id = 4


@pytest.mark.parametrizex("flush_data", [0, 1])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_ioctl_stop_clean_cache(flush_data):
    """
        title: Stop the cache without casadm.
        description: |
          Test of the ability to stop the cache with IOCTL request bypassing native
          OpenCAS manager - casadm. The cache is clean and no flush will be triggered during stop.
        pass_criteria:
          - Cache stopped successfully without any errors.
    """
    with TestRun.step("Prepare cache device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(2, Unit.GiB)])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Create IOCTL request for cache stopping."):
        stop_config = StopCacheRequest(cache_id=cache_id, flush_data=flush_data)

    with TestRun.step("Start cache before stop."):
        start_cache(cache_part, cache_id=cache_id, force=True)

    with TestRun.step("Stop cache with IOCTL request bypassing casadm."):
        cas_ioctl(stop_config)

    with TestRun.step(f"Check if cache is not running."):
        if len(get_caches()) != 0:
            TestRun.fail("Cache should be stopped despite the interruption!")


@pytest.mark.parametrizex("flush_data", [0, 1])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_ioctl_stop_interrupt_clean_cache(flush_data):
    """
        title: Interrupt cache stop without casadm.
        description: |
          Negative test of the ability to interrupt the cache stop with IOCTL request sent
          outside native OpenCAS manager - casadm. The cache is clean and no flush can be
          interrupted during stop.
        pass_criteria:
          - Cache is stopped.
    """
    with TestRun.step("Prepare cache device."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(128, Unit.GiB)])
        cache_part = cache_dev.partitions[0]

    with TestRun.step("Create IOCTL request for cache stop."):
        stop_config = StopCacheRequest(cache_id=cache_id, flush_data=flush_data)

    with TestRun.step("Start cache before stopping."):
        start_cache(cache_part, cache_id=cache_id, force=True)

    with TestRun.step("Clear dmesg."):
        common_utils.clear_dmesg()

    with TestRun.step("Interrupt stopping cache with IOCTL request bypassing casadm."):
        cas_ioctl(stop_config, True)
        sleep(8)    # wait for thread to finish asynchronously after interruption

    with TestRun.step(f"Check if cache is not running."):
        if len(get_caches()) > 0:
            TestRun.fail("Cache should be stopped despite the interruption!")
        else:
            TestRun.LOGGER.info('Stop process finished as expected.')

    with TestRun.step("Check dmesg for interruption log."):
        common_utils.check_dmesg(common_utils.interrupt_stop)
