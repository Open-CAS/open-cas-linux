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
from test_tools.cas_ioctl.cas_requests import StopCacheRequest
from test_tools.cas_ioctl.ioctl import cas_ioctl
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

