#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from time import sleep
import pytest

from api.cas import casadm, casadm_parser, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait, SeqCutOffPolicy
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.dd import Dd
from test_utils.output import CmdException
from test_utils.size import Size, Unit

cache_size = Size(2, Unit.GibiByte)


@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_concurrent_cores_flush(cache_mode):
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
    with TestRun.step("Prepare cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([cache_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([cache_size * 2] * 2)
        core_part1 = core_dev.partitions[0]
        core_part2 = core_dev.partitions[1]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step("Disable cleaning and sequential cutoff."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step(f"Add both core devices to cache."):
        core1 = cache.add_core(core_part1)
        core2 = cache.add_core(core_part2)

    with TestRun.step("Run workload on concurrent cores."):
        block_size = Size(4, Unit.MebiByte)
        count = int(cache_size.value / 2 / block_size.value)

        dd_pid = Dd().output(core1.system_path) \
            .input("/dev/urandom") \
            .block_size(block_size) \
            .count(count) \
            .run_in_background()

        Dd().output(core2.system_path) \
            .input("/dev/urandom") \
            .block_size(block_size) \
            .count(count) \
            .run()

    with TestRun.step("Check if both DD operations finished."):
        while TestRun.executor.run(f"ls /proc/{dd_pid}").exit_code == 0:
            sleep(1)

    with TestRun.step("Check if both cores contain dirty blocks."):
        if int(core1.get_dirty_blocks()) == 0:
            TestRun.fail("The first core does not contain dirty blocks.")
        if int(core2.get_dirty_blocks()) == 0:
            TestRun.fail("The second core does not contain dirty blocks.")
        core2_dirty_blocks_before = int(core2.get_dirty_blocks())

    with TestRun.step("Start flushing the first core."):
        TestRun.executor.run_in_background(
            cli.flush_core_cmd(str(cache.cache_id), str(core1.core_id))
        )

    with TestRun.step("Wait some time and start flushing the second core."):
        sleep(2)
        percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)
        while percentage < 40:
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)

        try:
            core2.flush_core()
            TestRun.fail("The first core is flushing right now so flush attempt of the second core "
                         "should fail.")
        except CmdException:
            TestRun.LOGGER.info("The first core is flushing right now so the second core's flush "
                                "fails as expected.")

    with TestRun.step("Wait for the first core to finish flushing."):
        try:
            percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)
            while percentage < 100:
                percentage = casadm_parser.get_flushing_progress(cache.cache_id, core1.core_id)
        except CmdException:
            TestRun.LOGGER.info("The first core is not flushing dirty data anymore.")

    with TestRun.step("Check number of dirty data on both cores."):
        if int(core1.get_dirty_blocks()) > 0:
            TestRun.LOGGER.error("The quantity of dirty cache lines on the first core "
                                 "after completed flush should be zero.")

        core2_dirty_blocks_after = int(core2.get_dirty_blocks())
        if core2_dirty_blocks_before != core2_dirty_blocks_after:
            TestRun.LOGGER.error("The quantity of dirty cache lines on the second core "
                                 "after failed flush should not change.")

    with TestRun.step("Stop cache."):
        cache.stop()
