#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random

import pytest

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.disk_utils import Filesystem
from test_utils.output import CmdException
from test_utils.size import Size, Unit

mount_point = "/mnt/cas"
cores_amount = 3


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_core_when_other_mounted_auto_numeration():
    """
    title: Remove one core when other are mounted - auto-numerated.
    description: |
        Test of the ability to remove the unmounted core from the cache when the other core
        is mounted and its ID starts with a different digit.
    pass_criteria:
      - No system crash.
      - Removing unmounted core finished with success.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(50, Unit.MebiByte)])
        core_device.create_partitions([Size(200, Unit.MebiByte)] * cores_amount)

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_device.partitions[0], force=True)

    with TestRun.step(f"Add {cores_amount} cores to cache and mount them except the first one"):
        free_core = cache.add_core(core_device.partitions[0])
        mounted_cores = []
        for i, part in enumerate(core_device.partitions[1:]):
            part.create_filesystem(Filesystem.xfs)
            mounted_cores.append(cache.add_core(part))
            mounted_cores[i].mount(
                mount_point=f"{mount_point}{cache.cache_id}-{mounted_cores[i].core_id}"
            )

    with TestRun.step("Remove the unmounted core"):
        try:
            cache.remove_core(free_core.core_id)
        except CmdException as exc:
            TestRun.fail(f"Cannot remove the unmounted core.\n{exc}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_core_when_other_mounted_custom_numeration():
    """
    title: Remove one core when other are mounted - custom numeration.
    description: |
        Test of the ability to remove the unmounted core from the cache when the other core
        is mounted and its ID starts with the same digit.
    pass_criteria:
      - No system crash.
      - Removing unmounted core finished with success.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(50, Unit.MebiByte)])
        core_device.create_partitions([Size(200, Unit.MebiByte)] * 3)

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_device.partitions[0], force=True)

    with TestRun.step(f"Add {cores_amount} cores to cache and mount them except the first one"):
        random_prefix = random.randint(1, 9)
        random_interfix = random.randint(1, 9)

        free_core = cache.add_core(core_dev=core_device.partitions[0], core_id=random_prefix)

        mounted_cores = []
        for i, part in enumerate(core_device.partitions[1:]):
            part.create_filesystem(Filesystem.xfs)
            mounted_cores.append(
                cache.add_core(core_dev=part, core_id=int(f"{random_prefix}{random_interfix}{i}"))
            )
            mounted_cores[i].mount(
                mount_point=f"{mount_point}{cache.cache_id}-{mounted_cores[i].core_id}"
            )

    with TestRun.step("Remove the unmounted core"):
        try:
            cache.remove_core(free_core.core_id)
        except CmdException as exc:
            TestRun.fail(f"Cannot remove the unmounted core.\n{exc}")
