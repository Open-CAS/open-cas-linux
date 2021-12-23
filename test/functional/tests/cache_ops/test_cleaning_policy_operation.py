#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


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
)
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_utils.size import Size, Unit
from test_utils.os_utils import Udev, sync
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
def test_cleaning_policies_in_write_back(cleaning_policy):
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

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()
        Udev.disable()

    with TestRun.step(
        f"Start cache in Write-Back mode with {cleaning_policy} cleaning policy"
    ):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WB, force=True)
        set_cleaning_policy_and_params(cache, cleaning_policy)

    with TestRun.step("Check for running CAS cleaner"):
        if TestRun.executor.run(f"pgrep {cas_cleaner_process_name}").exit_code != 0:
            TestRun.fail("CAS cleaner process is not running!")

    with TestRun.step(f"Add {cores_count} cores to the cache"):
        core = []
        for i in range(cores_count):
            core.append(cache.add_core(core_dev.partitions[i]))

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(cores_count):
            fio.add_job().target(core[i].path)
        fio.run()
        time.sleep(3)
        core_writes_before_wait_for_cleaning = (
            cache.get_statistics().block_stats.core.writes
        )

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check write statistics for core device"):
        core_writes_after_wait_for_cleaning = (
            cache.get_statistics().block_stats.core.writes
        )
        check_cleaning_policy_operation(
            cleaning_policy,
            core_writes_before_wait_for_cleaning,
            core_writes_after_wait_for_cleaning,
        )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()
        Udev.enable()


@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cleaning_policies_in_write_through(cleaning_policy):
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

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()
        Udev.disable()

    with TestRun.step(
        f"Start cache in Write-Through mode with {cleaning_policy} cleaning policy"
    ):
        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WT, force=True)
        set_cleaning_policy_and_params(cache, cleaning_policy)

    with TestRun.step("Check for running CAS cleaner"):
        if TestRun.executor.run(f"pgrep {cas_cleaner_process_name}").exit_code != 0:
            TestRun.fail("CAS cleaner process is not running!")

    with TestRun.step(f"Add {cores_count} cores to the cache"):
        core = []
        for i in range(cores_count):
            core.append(cache.add_core(core_dev.partitions[i]))

    with TestRun.step("Change cache mode to Write-Back"):
        cache.set_cache_mode(CacheMode.WB)

    with TestRun.step("Run 'fio'"):
        fio = fio_prepare()
        for i in range(cores_count):
            fio.add_job().target(core[i].path)
        fio.run()
        time.sleep(3)

    with TestRun.step("Change cache mode back to Write-Through"):
        cache.set_cache_mode(CacheMode.WT, flush=False)
        core_writes_before_wait_for_cleaning = (
            cache.get_statistics().block_stats.core.writes
        )

    with TestRun.step(f"Wait {time_to_wait} seconds"):
        time.sleep(time_to_wait)

    with TestRun.step("Check write statistics for core device"):
        core_writes_after_wait_for_cleaning = (
            cache.get_statistics().block_stats.core.writes
        )
        check_cleaning_policy_operation(
            cleaning_policy,
            core_writes_before_wait_for_cleaning,
            core_writes_after_wait_for_cleaning,
        )

    with TestRun.step("Stop all caches"):
        casadm.stop_all_caches()
        Udev.enable()


def storage_prepare():
    cache_dev = TestRun.disks["cache"]
    cache_dev.create_partitions([Size(1, Unit.GibiByte)])
    core_dev = TestRun.disks["core"]
    parts = [Size(2, Unit.GibiByte)] * cores_count
    core_dev.create_partitions(parts)
    return cache_dev, core_dev


def set_cleaning_policy_and_params(cache, cleaning_policy):
    if cleaning_policy != CleaningPolicy.DEFAULT:
        cache.set_cleaning_policy(cleaning_policy)
    current_cleaning_policy = cache.get_cleaning_policy()
    if current_cleaning_policy != cleaning_policy:
        TestRun.LOGGER.error(
            f"Cleaning policy is {current_cleaning_policy}, "
            f"should be {cleaning_policy}"
        )

    if cleaning_policy == CleaningPolicy.alru:
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
                    f"Wake Up time is {current_alru_params.wake_up_time}, "
                    f"should be {alru_params.wake_up_time}\n"
                )
            if current_alru_params.staleness_time != alru_params.staleness_time:
                failed_params += (
                    f"Staleness Time is {current_alru_params.staleness_time}, "
                    f"should be {alru_params.staleness_time}\n"
                )
            if current_alru_params.flush_max_buffers != alru_params.flush_max_buffers:
                failed_params += (
                    f"Flush Max Buffers is {current_alru_params.flush_max_buffers}, "
                    f"should be {alru_params.flush_max_buffers}\n"
                )
            if current_alru_params.activity_threshold != alru_params.activity_threshold:
                failed_params += (
                    f"Activity Threshold is {current_alru_params.activity_threshold}, "
                    f"should be {alru_params.activity_threshold}\n"
                )
            TestRun.LOGGER.error(f"ALRU parameters did not switch properly:\n{failed_params}")

    if cleaning_policy == CleaningPolicy.acp:
        acp_params = FlushParametersAcp()
        acp_params.wake_up_time = Time(milliseconds=100)
        acp_params.flush_max_buffers = 64
        cache.set_params_acp(acp_params)
        current_acp_params = cache.get_flush_parameters_acp()
        if current_acp_params != acp_params:
            failed_params = ""
            if current_acp_params.wake_up_time != acp_params.wake_up_time:
                failed_params += (
                    f"Wake Up time is {current_acp_params.wake_up_time}, "
                    f"should be {acp_params.wake_up_time}\n"
                )
            if current_acp_params.flush_max_buffers != acp_params.flush_max_buffers:
                failed_params += (
                    f"Flush Max Buffers is {current_acp_params.flush_max_buffers}, "
                    f"should be {acp_params.flush_max_buffers}\n"
                )
            TestRun.LOGGER.error(f"ACP parameters did not switch properly:\n{failed_params}")


def fio_prepare():
    fio = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .block_size(Size(4, Unit.KibiByte))
        .size(io_size)
        .read_write(ReadWrite.randwrite)
        .direct(1)
    )
    return fio


def check_cleaning_policy_operation(
    cleaning_policy,
    core_writes_before_wait_for_cleaning,
    core_writes_after_wait_for_cleaning,
):
    if cleaning_policy == CleaningPolicy.alru:
        if core_writes_before_wait_for_cleaning.value != 0:
            TestRun.LOGGER.error(
                "CAS cleaner started to clean dirty data right after IO! "
                "According to ALRU parameters set in this test cleaner should "
                "wait 10 seconds after IO before cleaning dirty data."
            )
        if core_writes_after_wait_for_cleaning <= core_writes_before_wait_for_cleaning:
            TestRun.LOGGER.error(
                "ALRU cleaning policy is not working properly! "
                "Core writes should increase in time while cleaning dirty data."
            )
    if cleaning_policy == CleaningPolicy.nop:
        if (
            core_writes_after_wait_for_cleaning.value != 0
            or core_writes_before_wait_for_cleaning.value != 0
        ):
            TestRun.LOGGER.error(
                "NOP cleaning policy is not working properly! "
                "There should be no core writes as there is no cleaning of dirty data."
            )
    if cleaning_policy == CleaningPolicy.acp:
        if core_writes_before_wait_for_cleaning.value == 0:
            TestRun.LOGGER.error(
                "CAS cleaner did not start cleaning dirty data right after IO! "
                "According to ACP policy cleaner should start "
                "cleaning dirty data right after IO."
            )
        if core_writes_after_wait_for_cleaning <= core_writes_before_wait_for_cleaning:
            TestRun.LOGGER.error(
                "ACP cleaning policy is not working properly! "
                "Core writes should increase in time while cleaning dirty data."
            )
