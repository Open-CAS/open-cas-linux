#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import time
import pytest

from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    FlushParametersAcp,
    FlushParametersAlru,
    Time,
    SeqCutOffPolicy,
)
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools.iostat import IOstatBasic
from type_def.size import Size, Unit
from test_tools.udev import Udev
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine


cores_count = 4
io_size = Size(10000, Unit.Blocks4096)

# time_to_wait in seconds
# For 4 cores and io_size = 10000 Blocks4096, 30 seconds of waiting should be enough
# for CAS cleaner to flush enough data for test purposes.
time_to_wait = 30

# Name of CAS cleaner to search for in running processes:
cas_cleaner_process_name = "cas_cl_"


@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policies_in_write_back(cleaning_policy: CleaningPolicy):
    """
    title: Test for cleaning policy operation in Write-Back cache mode.
    description: |
        Check if ALRU, NOP and ACP cleaning policies preserve their
        parameters when changed and if they flush dirty data properly
        in Write-Back cache mode.
    pass_criteria:
      - Flush parameters preserve their values when changed.
      - Dirty data is flushed or not according to the policy used.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev.create_partitions([Size(2, Unit.GibiByte)] * cores_count)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in Write-Back mode with {cleaning_policy} cleaning policy"):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WB, force=True)
        cache.set_cleaning_policy(cleaning_policy=cleaning_policy)
        set_cleaning_policy_params(cache, cleaning_policy)

    with TestRun.step("Check for running cleaner process"):
        output = TestRun.executor.run(f"pgrep {cas_cleaner_process_name}")
        if output.exit_code != 0:
            TestRun.fail("Cleaner process is not running!")

    with TestRun.step(f"Add {cores_count} cores to the cache"):
        cores = [cache.add_core(partition) for partition in core_dev.partitions]

    with TestRun.step("Run fio"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(4, Unit.KibiByte))
            .size(io_size)
            .read_write(ReadWrite.randwrite)
            .direct(True)
        )
        for core in cores:
            fio.add_job().target(core.path)

        fio.run()
        time.sleep(3)

        core_writes_before_wait_for_cleaning = cache.get_statistics().block_stats.core.writes

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check write statistics for core device"):
        core_writes_after_wait_for_cleaning = cache.get_statistics().block_stats.core.writes
        check_cleaning_policy_operation(
            cleaning_policy,
            core_writes_before_wait_for_cleaning,
            core_writes_after_wait_for_cleaning,
        )


@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policies_in_write_through(cleaning_policy: CleaningPolicy):
    """
    title: Test for cleaning policy operation in Write-Through cache mode.
    description: |
        Check if ALRU, NOP and ACP cleaning policies preserve their
        parameters when changed and if they flush dirty data properly
        in Write-Through cache mode.
    pass_criteria:
      - Flush parameters preserve their values when changed.
      - Dirty data is flushed or not according to the policy used.
    """

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        core_dev.create_partitions([Size(2, Unit.GibiByte)] * cores_count)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in Write-Through mode with {cleaning_policy} cleaning policy"):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WT, force=True)
        cache.set_cleaning_policy(cleaning_policy=cleaning_policy)
        set_cleaning_policy_params(cache, cleaning_policy)

    with TestRun.step("Check for running cleaner process"):
        output = TestRun.executor.run(f"pgrep {cas_cleaner_process_name}")
        if output.exit_code != 0:
            TestRun.fail("Cleaner process is not running!")

    with TestRun.step(f"Add {cores_count} cores to the cache"):
        cores = [cache.add_core(partition) for partition in core_dev.partitions]

    with TestRun.step("Change cache mode to Write-Back"):
        cache.set_cache_mode(CacheMode.WB)

    with TestRun.step("Populate cache with dirty data"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(4, Unit.KibiByte))
            .size(io_size)
            .read_write(ReadWrite.randwrite)
            .direct(1)
        )
        for core in cores:
            fio.add_job().target(core.path)
        fio.run()

    with TestRun.step("Change cache mode back to Write-Through"):
        cache.set_cache_mode(CacheMode.WT, flush=False)
        core_writes_before_wait_for_cleaning = cache.get_statistics().block_stats.core.writes

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check write statistics for core device"):
        core_writes_after_wait_for_cleaning = cache.get_statistics().block_stats.core.writes
        check_cleaning_policy_operation(
            cleaning_policy,
            core_writes_before_wait_for_cleaning,
            core_writes_after_wait_for_cleaning,
        )


def set_cleaning_policy_params(cache, cleaning_policy):
    current_cleaning_policy = cache.get_cleaning_policy()
    if current_cleaning_policy != cleaning_policy:
        TestRun.LOGGER.error(
            f"Cleaning policy is {current_cleaning_policy}, should be {cleaning_policy}"
        )

    match cleaning_policy:
        case CleaningPolicy.acp:
            acp_params = FlushParametersAcp()
            acp_params.wake_up_time = Time(milliseconds=100)
            acp_params.flush_max_buffers = 64
            cache.set_params_acp(acp_params)
            current_acp_params = cache.get_flush_parameters_acp()
            if current_acp_params != acp_params:
                failed_params = ""

                if current_acp_params.wake_up_time != acp_params.wake_up_time:
                    failed_params += (
                        f"Wake up time is {current_acp_params.wake_up_time}, "
                        f"should be {acp_params.wake_up_time}\n"
                    )
                if current_acp_params.flush_max_buffers != acp_params.flush_max_buffers:
                    failed_params += (
                        f"Flush max buffers is {current_acp_params.flush_max_buffers}, "
                        f"should be {acp_params.flush_max_buffers}\n"
                    )
                TestRun.LOGGER.error(f"ACP parameters did not switch properly:\n{failed_params}")

        case CleaningPolicy.alru:
            alru_params = FlushParametersAlru()
            alru_params.wake_up_time = Time(seconds=10)
            alru_params.staleness_time = Time(seconds=2)
            alru_params.flush_max_buffers = 100
            alru_params.activity_threshold = Time(milliseconds=1000)
            cache.set_params_alru(alru_params)
            current_alru_params = cache.get_flush_parameters_alru()
            if current_alru_params != alru_params:
                failed_params = ""
                if current_alru_params.wake_up_time != alru_params.wake_up_time:
                    failed_params += (
                        f"Wake up time is {current_alru_params.wake_up_time}, "
                        f"should be {alru_params.wake_up_time}\n"
                    )
                if current_alru_params.staleness_time != alru_params.staleness_time:
                    failed_params += (
                        f"Staleness time is {current_alru_params.staleness_time}, "
                        f"should be {alru_params.staleness_time}\n"
                    )
                if current_alru_params.flush_max_buffers != alru_params.flush_max_buffers:
                    failed_params += (
                        f"Flush max buffers is {current_alru_params.flush_max_buffers}, "
                        f"should be {alru_params.flush_max_buffers}\n"
                    )
                if current_alru_params.activity_threshold != alru_params.activity_threshold:
                    failed_params += (
                        f"Activity threshold is {current_alru_params.activity_threshold}, "
                        f"should be {alru_params.activity_threshold}\n"
                    )
                TestRun.LOGGER.error(f"ALRU parameters did not switch properly:\n{failed_params}")


def check_cleaning_policy_operation(
    cleaning_policy,
    core_writes_before_wait_for_cleaning,
    core_writes_after_wait_for_cleaning,
):
    match cleaning_policy:
        case CleaningPolicy.alru:
            if core_writes_before_wait_for_cleaning != Size.zero():
                TestRun.LOGGER.error(
                    "Cleaner process started to clean dirty data right after I/O! "
                    "According to ALRU parameters set in this test cleaner should "
                    "wait 10 seconds after I/O before cleaning dirty data"
                )
            if core_writes_after_wait_for_cleaning <= core_writes_before_wait_for_cleaning:
                TestRun.LOGGER.error(
                    "ALRU cleaning policy is not working properly! "
                    "Core writes should increase in time while cleaning dirty data"
                )
        case CleaningPolicy.nop:
            if (
                core_writes_after_wait_for_cleaning != Size.zero()
                or core_writes_before_wait_for_cleaning != Size.zero()
            ):
                TestRun.LOGGER.error(
                    "NOP cleaning policy is not working properly! "
                    "There should be no core writes as there is no cleaning of dirty data"
                )
        case CleaningPolicy.acp:
            if core_writes_before_wait_for_cleaning == Size.zero():
                TestRun.LOGGER.error(
                    "Cleaner process did not start cleaning dirty data right after I/O! "
                    "According to ACP policy cleaner should start "
                    "cleaning dirty data right after I/O"
                )
            if core_writes_after_wait_for_cleaning <= core_writes_before_wait_for_cleaning:
                TestRun.LOGGER.error(
                    "ACP cleaning policy is not working properly! "
                    "Core writes should increase in time while cleaning dirty data"
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_alru_change_trigger_dirty_ratio_during_io():
    """
    title: Test ALRU with trigger dirty ratio param during I/O
    description: |
        Verify that ALRU is able to start cleaning to expected dirty ratio under constant I/O.
    pass_criteria:
      - Dirty cache lines are being cleaned after trigger dirty ratio change during I/O.
      - Dirty cache lines are cleaned to expected dirty ratio after stopping I/O
    """
    iterations = 10

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]

        cache_size = Size(1, Unit.GiB)
        cache_dev.create_partitions([cache_size])
        core_dev.create_partitions([Size(2, Unit.GiB)])

    with TestRun.step(f"Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(cache_dev.partitions[0], force=True, cache_mode=CacheMode.WB)

    with TestRun.step("Add core"):
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Set params for ALRU cleaning policy"):
        params = FlushParametersAlru.default_alru_params()
        params.wake_up_time = Time(seconds=1)
        params.staleness_time = Time(seconds=3600)
        cache.set_params_alru(alru_params=params)

    with TestRun.step("Disable sequential cut-off and set cleaning to ALRU"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.alru)

    for _ in TestRun.iteration(
        range(0, iterations),
        "Start changing trigger dirty ratio param during I/O and check if flush occurred",
    ):

        params = FlushParametersAlru.default_alru_params()

        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .block_size(Size(4, Unit.KiB))
            .target(core)
            .direct()
            .time_based()
            .run_time(timedelta(minutes=10))
            .read_write(ReadWrite.randwrite)
        )

        dirty_ratio_test_threshold = random.randint(0, 100)

        with TestRun.step("Disable cache cleaning"):
            cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Start running I/O to exported object in background"):
            fio_pid = fio.run_in_background()

        with TestRun.step("Wait until dirty data on cache exceed dirty ratio threshold"):

            while TestRun.executor.check_if_process_exists(fio_pid):
                dirty_blocks_percentage_on_cache = cache.get_statistics(
                    percentage_val=True
                ).usage_stats.dirty

                if dirty_blocks_percentage_on_cache >= dirty_ratio_test_threshold:
                    break
                time.sleep(5)

        with TestRun.step("Set cache cleaning policy to alru"):
            params.trigger_dirty_ratio = dirty_ratio_test_threshold
            cache.set_params_alru(alru_params=params)

        with TestRun.step("Check if cleaning started after changing cleaning policy"):
            time.sleep(5)

            iostat_core = IOstatBasic.get_iostat_list([core_dev.get_device_id()])
            core_writes = iostat_core[0].total_writes

            if core_writes == Size.zero():
                TestRun.fail(f"Cleaning on cache haven`t started")

        with TestRun.step("Stop I/O to exported object"):
            TestRun.executor.kill_process(fio_pid)

        with TestRun.step("Check if cache has been cleaned to set threshold after stopping I/O"):
            max_cleaning_time = timedelta(seconds=60)
            t_end = time.time() + max_cleaning_time.seconds

            while time.time() < t_end:
                dirty_blocks_on_cache_before = cache.get_statistics(
                    percentage_val=True).usage_stats.dirty
                time.sleep(20)
                dirty_blocks_on_cache_after = cache.get_statistics(
                    percentage_val=True).usage_stats.dirty
                if dirty_blocks_on_cache_before == dirty_blocks_on_cache_after:
                    break

            dirty_blocks_cache_percentage = cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty

            if not dirty_ratio_test_threshold == dirty_blocks_cache_percentage:
                TestRun.fail("Dirty block percentage outside of defined range")

        with TestRun.step("Purge cache"):
            casadm.purge_cache(cache_id=cache.cache_id)
