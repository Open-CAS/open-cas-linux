#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.os_utils import Udev
from test_utils.size import Unit, Size
from test_tools.dd import Dd
from test_tools.iostat import IOstatBasic

dd_count = 100


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("cache_mode", [CacheMode.WT, CacheMode.WA, CacheMode.WB])
@pytest.mark.CI()
def test_ci_read(cache_mode):
    """
    title: Verification test for write mode: write around
    description: Verify if write mode: write around, works as expected and cache only reads
    and does not cache write
    pass criteria:
    - writes are not cached
    - reads are cached
    """

    with TestRun.step("Prepare partitions"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache with cache_mode={cache_mode}"):
        cache = casadm.start_cache(cache_dev=cache_device, cache_id=1, force=True,
                                   cache_mode=cache_mode)
        casadm.add_core(cache, core_device)

    with TestRun.step("Insert data into the cache using reads"):
        data_read = Size(dd_count, Unit.Blocks4096)
        dd = (
            Dd()
            .input("/dev/cas1-1")
            .output("/dev/null")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .iflag("direct")
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat = IOstatBasic.get_iostat_list([cache_device.parent_device])
        read_cache_1 = iostat[0].total_reads

    with TestRun.step("Generate cache hits using reads"):
        dd = (
            Dd()
            .input("/dev/cas1-1")
            .output("/dev/null")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .iflag("direct")
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat = IOstatBasic.get_iostat_list([cache_device.parent_device])
        read_cache_2 = iostat[0].total_reads

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Enable udev"):
        Udev.enable()

    with TestRun.step("Check if reads are cached"):
        read_cache_delta = read_cache_2 - read_cache_1
        if read_cache_delta == data_read:
            TestRun.LOGGER.info(f"Reads from cache: {read_cache_delta} == {data_read}")
        else:
            TestRun.LOGGER.error(f"Reads from cache: {read_cache_delta} != {data_read}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.CI()
def test_ci_write_around_write():
    with TestRun.step("Prepare partitions"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start CAS Linux in Write Around mode"):
        cache = casadm.start_cache(cache_dev=cache_device, cache_id=1, force=True,
                                   cache_mode=CacheMode.WA)
        casadm.add_core(cache, core_device)

    with TestRun.step("Collect iostat before I/O"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        write_core_0 = iostat_core[0].total_writes

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        write_cache_0 = iostat_cache[0].total_writes

    with TestRun.step("Submit writes to exported object"):
        data_write = Size(dd_count, Unit.Blocks4096)
        dd = (
            Dd()
            .input("/dev/zero")
            .output("/dev/cas1-1")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .oflag("direct")
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        write_core_1 = iostat_core[0].total_writes
        read_core_1 = iostat_core[0].total_reads

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        write_cache_1 = iostat_cache[0].total_writes
        read_cache_1 = iostat_cache[0].total_reads

    with TestRun.step("Submit reads to exported object"):
        dd = (
            Dd()
            .input("/dev/cas1-1")
            .output("/dev/null")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .iflag("direct")
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        read_core_2 = iostat_core[0].total_reads

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        read_cache_2 = iostat_cache[0].total_reads

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Enable udev"):
        Udev.enable()

    with TestRun.step("Verify that writes propagated to core"):
        write_core_delta_1 = write_core_1 - write_core_0
        if write_core_delta_1 == data_write:
            TestRun.LOGGER.info(f"Writes to core: {write_core_delta_1} == {data_write}")
        else:
            TestRun.LOGGER.error(f"Writes to core: {write_core_delta_1} != {data_write}")

    with TestRun.step("Verify that writes did not insert into cache"):
        write_cache_delta_1 = write_cache_1 - write_cache_0
        if write_cache_delta_1.value == 0:
            TestRun.LOGGER.info(f"Writes to cache: {write_cache_delta_1} == 0")
        else:
            TestRun.LOGGER.error(f"Writes to cache: {write_cache_delta_1} != 0")

    with TestRun.step("Verify that reads propagated to core"):
        read_core_delta_2 = read_core_2 - read_core_1
        if read_core_delta_2 == data_write:
            TestRun.LOGGER.info(f"Reads from core: {read_core_delta_2} == {data_write}")
        else:
            TestRun.LOGGER.error(f"Reads from core: {read_core_delta_2} != {data_write}")

    with TestRun.step("Verify that reads did not occur on cache"):
        read_cache_delta_2 = read_cache_2 - read_cache_1
        if read_cache_delta_2.value == 0:
            TestRun.LOGGER.info(f"Reads from cache: {read_cache_delta_2} == 0")
        else:
            TestRun.LOGGER.error(f"Reads from cache: {read_cache_delta_2} != 0")



@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.CI()
def test_ci_write_through_write():
    with TestRun.step("Prepare partitions"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(2, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start CAS Linux in Write Through mode"):
        cache = casadm.start_cache(cache_dev=cache_device, cache_id=1, force=True,
                                   cache_mode=CacheMode.WT)
        casadm.add_core(cache, core_device)

    with TestRun.step("Collect iostat before I/O"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        write_core_0 = iostat_core[0].total_writes

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        write_cache_0 = iostat_cache[0].total_writes

    with TestRun.step("Insert data into the cache using writes"):
        data_write = Size(dd_count, Unit.Blocks4096)
        dd = (
            Dd()
            .input("/dev/zero")
            .output("/dev/cas1-1")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .oflag("direct")
            .seek(20000)
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        write_core_1 = iostat_core[0].total_writes
        read_core_1 = iostat_core[0].total_reads

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        write_cache_1 = iostat_cache[0].total_writes
        read_cache_1 = iostat_cache[0].total_reads

    with TestRun.step("Generate cache hits using reads"):
        dd = (
            Dd()
            .input("/dev/cas1-1")
            .output("/dev/null")
            .count(dd_count)
            .block_size(Size(1, Unit.Blocks4096))
            .iflag("direct")
            .skip(20000)
        )
        dd.run()

    with TestRun.step("Collect iostat"):
        iostat_core = IOstatBasic.get_iostat_list([core_device.parent_device])
        read_core_2 = iostat_core[0].total_reads

        iostat_cache = IOstatBasic.get_iostat_list([cache_device.parent_device])
        read_cache_2 = iostat_cache[0].total_reads

    with TestRun.step("Stop cache"):
        cache.stop()

    with TestRun.step("Enable udev"):
        Udev.enable()

    with TestRun.step("Verify that writes propagated to core"):
        write_core_delta_1 = write_core_1 - write_core_0
        if write_core_delta_1 == data_write:
            TestRun.LOGGER.info(f"Writes to core: {write_core_delta_1} == {data_write}")
        else:
            TestRun.LOGGER.error(f"Writes to core: {write_core_delta_1} != {data_write}")

    with TestRun.step("Verify that writes inserted into cache"):
        write_cache_delta_1 = write_cache_1 - write_cache_0
        if write_cache_delta_1 == data_write:
            TestRun.LOGGER.info(f"Writes to cache: {write_cache_delta_1} == {data_write}")
        else:
            TestRun.LOGGER.error(f"Writes to cache: {write_cache_delta_1} != {data_write}")

    with TestRun.step("Verify that reads did not propagate to core"):
        read_core_delta_2 = read_core_2 - read_core_1
        if read_core_delta_2.value == 0:
            TestRun.LOGGER.info(f"Reads from core: {read_core_delta_2} == 0")
        else:
            TestRun.LOGGER.error(f"Reads from core: {read_core_delta_2} != 0")

    with TestRun.step("Verify that reads were hits from cache"):
        read_cache_delta_2 = read_cache_2 - read_cache_1
        if read_cache_delta_2 == data_write:
            TestRun.LOGGER.info(f"Reads from cache: {read_cache_delta_2} == {data_write}")
        else:
            TestRun.LOGGER.error(f"Reads from cache: {read_cache_delta_2} != {data_write}")
