#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import json

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from api.cas.casadm import StatsFilter
from api.cas.statistics import get_stats_dict, get_stat_value, OperationType
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.udev import Udev
from types.size import Size, Unit

iterations = 10
dd_block_size = Size(1, Unit.Blocks4096)
dd_count = 10
cores_no = 3


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("cache_mode", CacheMode)
def test_block_stats_write_miss(cache_mode: CacheMode):
    """
    title: Block statistics after write miss operations
    description: |
        Perform write miss operations to cached volume and check if block stats values are correct
        for configured cache mode.
    pass_criteria:
      - Correct block stats values
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * cores_no)

        cache_device = cache_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache and set NOP cleaning policy"):
        cache = casadm.start_cache(cache_device, cache_mode=cache_mode, force=True)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Add core devices"):
        cores = [cache.add_core(part) for part in core_device.partitions]

    with TestRun.step("Reset cache stats"):
        cache.reset_counters()

    with TestRun.step("Write data in parts to exported objects and verify block statistics "
                      "after each part is done"):
        expected_zero_stats = get_expected_zero_stats(cache_mode, OperationType.write)

        dd_seek = 0
        dd = (
            Dd()
            .input("/dev/zero")
            .count(dd_count)
            .block_size(dd_block_size)
            .oflag("direct")
        )
        for i in range(iterations):
            core_stat_expected = dd_block_size * dd_count * (i + 1)
            core_stat_expected.set_unit(Unit.Blocks4096)
            dd.seek(dd_seek)
            for j, core in enumerate(cores):
                # expect previous iterations + already written data in this iteration
                cache_stat_expected = dd_block_size * dd_count * (i * cores_no + j + 1)
                cache_stat_expected.set_unit(Unit.Blocks4096)
                dd.output(core.path)
                dd.run()
                cache_stats = get_stats_dict(filter=[StatsFilter.blk], cache_id=cache.cache_id)
                core_stats = get_stats_dict(
                    filter=[StatsFilter.blk], cache_id=cache.cache_id, core_id=core.core_id
                )

                # Check cache stats after write operation
                fail = False
                for key, value in cache_stats.items():
                    if key.endswith('[%]'):
                        continue
                    stat = get_stat_value(cache_stats, key)
                    if any(key.startswith(s) for s in expected_zero_stats):
                        if stat != Size.zero():
                            TestRun.LOGGER.error(f"{key} has non-zero value of {stat}")
                            fail = True
                    elif stat != cache_stat_expected:
                        TestRun.LOGGER.error(
                            f"{key} has invalid value of {stat}\n"
                            f"expected: {cache_stat_expected}"
                        )
                        fail = True
                if fail:
                    TestRun.fail(
                        "Incorrect cache block stats\n"
                        f"iteration {i}, core id: {core.core_id}\n"
                        f"cache_stats:\n{json.dumps(cache_stats, indent=0)}"
                    )

                # Check per-core stats
                for key, value in core_stats.items():
                    if key.endswith('[%]'):
                        continue
                    stat = get_stat_value(core_stats, key)
                    if any(key.startswith(s) for s in expected_zero_stats):
                        if stat != Size.zero():
                            TestRun.LOGGER.error(f"{key} has non-zero value of {stat}")
                            fail = True
                    elif stat != core_stat_expected:
                        TestRun.LOGGER.error(
                            f"{key} has invalid value of {stat}\n"
                            f"expected: {core_stat_expected}"
                        )
                if fail:
                    TestRun.fail(
                        "Incorrect core block stats\n"
                        f"iteration {i}, core id: {core.core_id}\n"
                        f"core_stats:\n{json.dumps(core_stats, indent=0)}"
                    )
            dd_seek += dd_count


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("cache_mode", CacheMode)
def test_block_stats_read_miss(cache_mode: CacheMode):
    """
    title: Block statistics after read miss operations
    description: |
        Perform read miss operations from cached volume and check if block stats values are correct
        for configured cache mode.
    pass_criteria:
      - Correct block stats values
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * cores_no)

        cache_device = cache_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache and set NOP cleaning policy"):
        cache = casadm.start_cache(cache_device, cache_mode=cache_mode, force=True)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Add core devices"):
        cores = [cache.add_core(part) for part in core_device.partitions]

    with TestRun.step("Reset cache stats"):
        cache.reset_counters()

    with TestRun.step("Read data in parts from exported objects and verify block statistics "
                      "after each part is done"):
        expected_zero_stats = get_expected_zero_stats(cache_mode, OperationType.read)

        dd_skip = 0
        dd = (
            Dd()
            .output("/dev/null")
            .count(dd_count)
            .block_size(dd_block_size)
            .iflag("direct")
        )
        for i in range(iterations):
            core_stat_expected = dd_block_size * dd_count * (i + 1)
            core_stat_expected.set_unit(Unit.Blocks4096)
            dd.skip(dd_skip)
            for j, core in enumerate(cores):
                # expect previous iterations + already read data in this iteration
                cache_stat_expected = dd_block_size * dd_count * (i * cores_no + j + 1)
                cache_stat_expected.set_unit(Unit.Blocks4096)
                dd.input(core.path)
                dd.run()
                cache_stats = get_stats_dict(filter=[StatsFilter.blk], cache_id=cache.cache_id)
                core_stats = get_stats_dict(
                    filter=[StatsFilter.blk], cache_id=cache.cache_id, core_id=core.core_id
                )

                # Check cache stats after read operation
                fail = False
                for key, value in cache_stats.items():
                    if key.endswith('[%]'):
                        continue
                    stat = get_stat_value(cache_stats, key)
                    if any(key.startswith(s) for s in expected_zero_stats):
                        if stat != Size.zero():
                            TestRun.LOGGER.error(f"{key} has non-zero value of {stat}")
                            fail = True
                    elif stat != cache_stat_expected:
                        TestRun.LOGGER.error(
                            f"{key} has invalid value of {stat}\n"
                            f"expected: {cache_stat_expected}"
                        )
                        fail = True
                if fail:
                    TestRun.fail(
                        "Incorrect cache block stats\n"
                        f"iteration {i}, core id: {core.core_id}\n"
                        f"cache_stats:\n{json.dumps(cache_stats, indent=0)}"
                    )

                # Check per-core stats
                for key, value in core_stats.items():
                    if key.endswith('[%]'):
                        continue
                    stat = get_stat_value(core_stats, key)
                    if any(key.startswith(s) for s in expected_zero_stats):
                        if stat != Size.zero():
                            TestRun.LOGGER.error(f"{key} has non-zero value of {stat}")
                            fail = True
                    elif stat != core_stat_expected:
                        TestRun.LOGGER.error(
                            f"{key} has invalid value of {stat}\n"
                            f"expected: {core_stat_expected}"
                        )
                if fail:
                    TestRun.fail(
                        "Incorrect core block stats\n"
                        f"iteration {i}, core id: {core.core_id}\n"
                        f"core_stats:\n{json.dumps(core_stats, indent=0)}"
                    )
            dd_skip += dd_count


def get_expected_zero_stats(cache_mode: CacheMode, direction: OperationType):
    traits = CacheMode.get_traits(cache_mode)

    stat_list = ["Reads from cache"]
    if direction == OperationType.write:
        stat_list.append("Reads from core")
        stat_list.append("Reads from exported object")
    if direction == OperationType.read or CacheModeTrait.LazyWrites in traits:
        stat_list.append("Writes to core")
    if direction == OperationType.read:
        stat_list.append("Writes to exported object")
    if ((direction == OperationType.read and CacheModeTrait.InsertRead not in traits)
            or (direction == OperationType.write and CacheModeTrait.InsertWrite not in traits)):
        stat_list.append("Writes to cache")
        stat_list.append("Total to/from cache")
    if direction == OperationType.write and CacheModeTrait.LazyWrites in traits:
        stat_list.append("Total to/from core")

    return stat_list
