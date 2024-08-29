#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.CI
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_start_cache_add_core():
    """
    title: Basic test for starting cache and adding core.
    description: |
        Test for start cache and add core.
    pass_criteria:
      - Cache started successfully.
      - Core added successfully.
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(500, Unit.MebiByte)])
        core_dev.create_partitions([Size(2, Unit.GibiByte)])

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_dev.partitions[0], force=True)

    with TestRun.step("Add core"):
        cache.add_core(core_dev.partitions[0])
