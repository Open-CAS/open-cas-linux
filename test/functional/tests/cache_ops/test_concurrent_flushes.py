#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from time import sleep

from api.cas import casadm, casadm_parser, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k]))
def test_concurrent_cores_flush(cache_mode: CacheMode):
    """
    title: Fail to flush two cores simultaneously.
    description: |
        CAS should return an error on attempt to flush second core if there is already
        one flush in progress.
    pass_criteria:
      - No system crash.
      - First core flushing should finish successfully.
      - It should not be possible to run flushing command on cores within
        the same cache simultaneously.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev.create_partitions([Size(5, Unit.GibiByte)] * 2)

        cache_part = cache_dev.partitions[0]
        core_part1 = core_dev.partitions[0]
        core_part2 = core_dev.partitions[1]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step(f"Add both core devices to cache"):
        core1 = cache.add_core(core_part1)
        core2 = cache.add_core(core_part2)

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Run concurrent fio on both cores"):
        fio_pids = []
        for core in [core1, core2]:
            fio = (
                Fio()
                .create_command()
                .io_engine(IoEngine.libaio)
                .target(core.path)
                .size(core.size)
                .block_size(Size(4, Unit.MebiByte))
                .read_write(ReadWrite.write)
                .direct(1)
            )
            fio_pid = fio.run_in_background()
            fio_pids.append(fio_pid)

        for fio_pid in fio_pids:
            if not TestRun.executor.check_if_process_exists(fio_pid):
                TestRun.fail("Fio failed to start")

    with TestRun.step("Wait for fio to finish"):
        for fio_pid in fio_pids:
            while TestRun.executor.check_if_process_exists(fio_pid):
                sleep(1)

    with TestRun.step("Check if both cores contain dirty blocks"):
        if core1.get_dirty_blocks() == Size.zero():
            TestRun.fail("The first core does not contain dirty blocks")
        if core2.get_dirty_blocks() == Size.zero():
            TestRun.fail("The second core does not contain dirty blocks")
        core2_dirty_blocks_before = core2.get_dirty_blocks()

    with TestRun.step("Start flushing the first core in background"):
        output_pid = TestRun.executor.run_in_background(
            cli.flush_core_cmd(str(cache.cache_id), str(core1.core_id))
        )
        if not TestRun.executor.check_if_process_exists(output_pid):
            TestRun.fail("Failed to start core flush in background")

    with TestRun.step("Wait until flush starts"):
        while TestRun.executor.check_if_process_exists(output_pid):
            try:
                casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)
                break
            except CmdException:
                pass

    with TestRun.step(
        "Wait until first core reach 40% flush and start flush operation on the second core"
    ):
        percentage = 0
        while percentage < 40:
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)

        try:
            core2.flush_core()
            TestRun.fail(
                "The first core is flushing right now so flush attempt of the second core "
                "should fail"
            )
        except CmdException:
            TestRun.LOGGER.info(
                "The first core is flushing right now so the second core's flush "
                "fails as expected"
            )

    with TestRun.step("Wait for the first core to finish flushing"):
        try:
            percentage = 0
            while percentage < 100:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)
                sleep(1)
        except CmdException:
            TestRun.LOGGER.info("The first core is not flushing dirty data anymore")

    with TestRun.step("Check number of dirty data on both cores"):
        if core1.get_dirty_blocks() > Size.zero():
            TestRun.LOGGER.error(
                "The quantity of dirty cache lines on the first core "
                "after completed flush should be zero"
            )

        core2_dirty_blocks_after = core2.get_dirty_blocks()
        if core2_dirty_blocks_before != core2_dirty_blocks_after:
            TestRun.LOGGER.error(
                "The quantity of dirty cache lines on the second core "
                "after failed flush should not change"
            )


@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_concurrent_caches_flush(cache_mode: CacheMode):
    """
    title: Success to flush two caches simultaneously.
    description: |
        CAS should successfully flush multiple caches if there is already other flush in progress.
    pass_criteria:
      - No system crash.
      - Flush for each cache should finish successfully.
    """
    caches_number = 3

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(2, Unit.GibiByte)] * caches_number)
        core_dev.create_partitions([Size(2, Unit.GibiByte) * 2] * caches_number)

    with TestRun.step(f"Start {caches_number} caches"):
        caches = [
            casadm.start_cache(cache_dev=part, cache_mode=cache_mode, force=True)
            for part in cache_dev.partitions
        ]

    with TestRun.step("Disable cleaning and sequential cutoff"):
        for cache in caches:
            cache.set_cleaning_policy(CleaningPolicy.nop)
            cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step(f"Add core devices to caches"):
        cores = [cache.add_core(core_dev=core_dev.partitions[i]) for i, cache in enumerate(caches)]

    with TestRun.step("Run fio on all cores"):
        fio_pids = []
        for core in cores:
            fio = (
                Fio()
                .create_command()
                .target(core)
                .io_engine(IoEngine.libaio)
                .block_size(Size(4, Unit.MebiByte))
                .size(core.size)
                .read_write(ReadWrite.write)
                .direct(1)
            )
            fio_pids.append(fio.run_in_background())

    with TestRun.step("Check if each cache is full of dirty blocks"):
        for cache in caches:
            if not cache.get_dirty_blocks() != core.size:
                TestRun.fail(f"The cache {cache.cache_id} does not contain dirty blocks")

    with TestRun.step("Start flush operation on all caches simultaneously"):
        flush_pids = [
            TestRun.executor.run_in_background(cli.flush_cache_cmd(str(cache.cache_id)))
            for cache in caches
        ]

    with TestRun.step("Wait for all caches to finish flushing"):
        for flush_pid in flush_pids:
            while TestRun.executor.check_if_process_exists(flush_pid):
                sleep(1)

    with TestRun.step("Check number of dirty data on each cache"):
        for cache in caches:
            if cache.get_dirty_blocks() > Size.zero():
                TestRun.LOGGER.error(
                    f"The quantity of dirty cache lines on the cache "
                    f"{str(cache.cache_id)} after complete flush should be zero"
                )
