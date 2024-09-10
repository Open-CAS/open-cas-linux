#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, cli, cli_messages
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_multilevel_core():
    """
    title: Test of the ability to remove a core used in a multilevel cache.
    description: |
        Negative test if OpenCAS does not allow to remove a core when the related exported object
        is used as a core device for another cache instance.
    pass_criteria:
      - No system crash.
      - OpenCAS does not allow removing a core used in a multilevel cache instance.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(512, Unit.MebiByte)] * 2)
        core_dev.create_partitions([Size(1, Unit.GibiByte)])

    with TestRun.step("Start the first cache instance"):
        cache1 = casadm.start_cache(cache_dev.partitions[0], force=True)

    with TestRun.step("Add a core device to the first cache instance."):
        core1 = cache1.add_core(core_dev.partitions[0])

    with TestRun.step("Start the second cache instance"):
        cache2 = casadm.start_cache(cache_dev.partitions[1], force=True)

    with TestRun.step(
        "Add the first cache's exported object as a core to the second cache instance."
    ):
        cache2.add_core(core1)

    with TestRun.step("Try to remove core from the first level cache."):
        output = TestRun.executor.run_expect_fail(
            cli.remove_core_cmd(
                cache_id=str(cache1.cache_id), core_id=str(core1.core_id), force=True
            )
        )
        cli_messages.check_stderr_msg(output, cli_messages.remove_multilevel_core)
