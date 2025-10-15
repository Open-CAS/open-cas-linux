#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest
import random

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    FlushParametersAcp,
    FlushParametersAlru,
    SeqCutOffParameters,
    SeqCutOffPolicy,
    Time,
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from type_def.size import Size, Unit


# There should be at least 2 cache instances and 2 cores per cache
# for this test to run correctly.
caches_count = 2
cores_per_cache = 2
# Number of parameter checks for every cache mode and policy variation used in test.
# Every check is performed with different random value of every parameter within
# given policy.
number_of_checks = 10


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_set_get_seq_cutoff_params(cache_mode):
    """
    title: Test for setting and reading sequential cutoff parameters.
    description: |
        Verify that it is possible to set and read all available sequential cutoff
        parameters using casadm --set-param and --get-param options.
    pass_criteria:
      - All sequential cutoff parameters are set to given values.
      - All sequential cutoff parameters displays proper values.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_parts = [Size(1, Unit.GibiByte)] * caches_count
        cache_dev.create_partitions(cache_parts)

        core_dev = TestRun.disks["core"]
        core_parts = [Size(2, Unit.GibiByte)] * cores_per_cache * caches_count
        core_dev.create_partitions(core_parts)

    with TestRun.step(
        f"Start {caches_count} caches in {cache_mode} cache mode "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches = [
            casadm.start_cache(part, cache_mode, force=True) for part in cache_dev.partitions
        ]

        cores = [
            [
                caches[i].add_core(
                    core_dev.partitions[i * cores_per_cache + j]
                ) for j in range(cores_per_cache)
            ] for i in range(caches_count)
        ]

    with TestRun.step("Check sequential cutoff default parameters"):
        default_seq_cutoff_params = SeqCutOffParameters.default_seq_cut_off_params()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                check_seq_cutoff_parameters(cores[i][j], default_seq_cutoff_params)

    with TestRun.step(
        "Set new random values for sequential cutoff parameters for one core only"
    ):
        for check in range(number_of_checks):
            random_seq_cutoff_params = new_seq_cutoff_parameters_random_values()
            cores[0][0].set_seq_cutoff_parameters(random_seq_cutoff_params)

            # Check changed parameters for first core:
            check_seq_cutoff_parameters(cores[0][0], random_seq_cutoff_params)

            # Check default parameters for other cores:
            for j in range(1, cores_per_cache):
                check_seq_cutoff_parameters(cores[0][j], default_seq_cutoff_params)
            for i in range(1, caches_count):
                for j in range(cores_per_cache):
                    check_seq_cutoff_parameters(cores[i][j], default_seq_cutoff_params)

    with TestRun.step(
        "Set new random values for sequential cutoff parameters "
        "for all cores within given cache instance"
    ):
        for check in range(number_of_checks):
            random_seq_cutoff_params = new_seq_cutoff_parameters_random_values()
            caches[0].set_seq_cutoff_parameters(random_seq_cutoff_params)

            # Check changed parameters for first cache instance:
            for j in range(cores_per_cache):
                check_seq_cutoff_parameters(cores[0][j], random_seq_cutoff_params)

            # Check default parameters for other cache instances:
            for i in range(1, caches_count):
                for j in range(cores_per_cache):
                    check_seq_cutoff_parameters(cores[i][j], default_seq_cutoff_params)

    with TestRun.step(
        "Set new random values for sequential cutoff parameters for all cores"
    ):
        for check in range(number_of_checks):
            seq_cutoff_params = []
            for i in range(caches_count):
                for j in range(cores_per_cache):
                    random_seq_cutoff_params = new_seq_cutoff_parameters_random_values()
                    seq_cutoff_params.append(random_seq_cutoff_params)
                    cores[i][j].set_seq_cutoff_parameters(random_seq_cutoff_params)
            for i in range(caches_count):
                for j in range(cores_per_cache):
                    check_seq_cutoff_parameters(
                        cores[i][j], seq_cutoff_params[i * cores_per_cache + j]
                    )


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cleaning_policy", [CleaningPolicy.alru, CleaningPolicy.acp])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_set_get_cleaning_params(cache_mode, cleaning_policy):
    """
    title: Test for setting and reading cleaning parameters.
    description: |
        Verify that it is possible to set and read all available cleaning
        parameters for all cleaning policies using casadm --set-param and
        --get-param options.
    pass_criteria:
      - All cleaning parameters are set to given values.
      - All cleaning parameters displays proper values.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_parts = [Size(1, Unit.GibiByte)] * caches_count
        cache_dev.create_partitions(cache_parts)

        core_dev = TestRun.disks["core"]
        core_parts = [Size(2, Unit.GibiByte)] * cores_per_cache * caches_count
        core_dev.create_partitions(core_parts)

    with TestRun.step(
        f"Start {caches_count} caches in {cache_mode} cache mode "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches = [
            casadm.start_cache(part, cache_mode, force=True) for part in cache_dev.partitions
        ]

        for i in range(caches_count):
            for j in range(cores_per_cache):
                caches[i].add_core(core_dev.partitions[i * cores_per_cache + j])

    with TestRun.step(f"Set cleaning policy to {cleaning_policy}"):
        if cleaning_policy != CleaningPolicy.DEFAULT:
            for i in range(caches_count):
                caches[i].set_cleaning_policy(cleaning_policy)
        for i in range(caches_count):
            current_cleaning_policy = caches[i].get_cleaning_policy()
            if current_cleaning_policy != cleaning_policy:
                TestRun.fail(
                    f"Cleaning policy for cache nr {caches[i].cache_id} "
                    f"is {current_cleaning_policy}, should be {cleaning_policy}"
                )

    with TestRun.step(f"Check {cleaning_policy} cleaning policy default parameters"):
        if cleaning_policy == CleaningPolicy.alru:
            default_cleaning_params = FlushParametersAlru.default_alru_params()
        if cleaning_policy == CleaningPolicy.acp:
            default_cleaning_params = FlushParametersAcp.default_acp_params()
        for i in range(caches_count):
            check_cleaning_parameters(
                caches[i], cleaning_policy, default_cleaning_params
            )

    with TestRun.step(
        f"Set new random values for {cleaning_policy} "
        f"cleaning policy parameters for one cache instance"
    ):
        for check in range(number_of_checks):
            random_cleaning_params = new_cleaning_parameters_random_values(
                cleaning_policy
            )
            if cleaning_policy == CleaningPolicy.alru:
                caches[0].set_params_alru(random_cleaning_params)
            if cleaning_policy == CleaningPolicy.acp:
                caches[0].set_params_acp(random_cleaning_params)

            # Check changed parameters for first cache instance:
            check_cleaning_parameters(
                caches[0], cleaning_policy, random_cleaning_params
            )

            # Check default parameters for other cache instances:
            for i in range(1, caches_count):
                check_cleaning_parameters(
                    caches[i], cleaning_policy, default_cleaning_params
                )

    with TestRun.step(
        f"Set new random values for {cleaning_policy} "
        f"cleaning policy parameters for all cache instances"
    ):
        for check in range(number_of_checks):
            cleaning_params = []
            for i in range(caches_count):
                random_cleaning_params = new_cleaning_parameters_random_values(
                    cleaning_policy
                )
                cleaning_params.append(random_cleaning_params)
                if cleaning_policy == CleaningPolicy.alru:
                    caches[i].set_params_alru(random_cleaning_params)
                if cleaning_policy == CleaningPolicy.acp:
                    caches[i].set_params_acp(random_cleaning_params)
            for i in range(caches_count):
                check_cleaning_parameters(
                    caches[i], cleaning_policy, cleaning_params[i]
                )


def new_seq_cutoff_parameters_random_values():
    return SeqCutOffParameters(
        threshold=Size(random.randrange(1, 1000000), Unit.KibiByte),
        policy=random.choice(list(SeqCutOffPolicy)),
        promotion_count=random.randrange(1, 65535)
    )


def new_cleaning_parameters_random_values(cleaning_policy):
    if cleaning_policy == CleaningPolicy.alru:
        alru_params_range = FlushParametersAlru.alru_params_range()
        wake_up_time_random_value = Time(
            seconds=random.randint(*alru_params_range.wake_up_time)
        )
        staleness_time_random_value = Time(
            seconds=random.randint(*alru_params_range.staleness_time)
        )
        flush_max_buffers_random_value = random.randint(
            *alru_params_range.flush_max_buffers
        )
        activity_threshold_random_value = Time(
            milliseconds=random.randint(*alru_params_range.activity_threshold)
        )
        dirty_ratio_threshold_random_value = random.randint(
            *alru_params_range.dirty_ratio_threshold
        )
        dirty_ratio_inertia_random_value = Size(random.randint(
            *alru_params_range.dirty_ratio_inertia),
            Unit.MebiByte,
        )
        cleaning_params = FlushParametersAlru()
        cleaning_params.wake_up_time = wake_up_time_random_value
        cleaning_params.staleness_time = staleness_time_random_value
        cleaning_params.flush_max_buffers = flush_max_buffers_random_value
        cleaning_params.activity_threshold = activity_threshold_random_value
        cleaning_params.dirty_ratio_threshold = dirty_ratio_threshold_random_value
        cleaning_params.dirty_ratio_inertia = dirty_ratio_inertia_random_value
        

    if cleaning_policy == CleaningPolicy.acp:
        acp_params_range = FlushParametersAcp().acp_params_range()
        wake_up_time_random_value = Time(
            milliseconds=random.randint(*acp_params_range.wake_up_time)
        )
        flush_max_buffers_random_value = random.randint(
            *acp_params_range.flush_max_buffers
        )
        cleaning_params = FlushParametersAcp()
        cleaning_params.wake_up_time = wake_up_time_random_value
        cleaning_params.flush_max_buffers = flush_max_buffers_random_value

    return cleaning_params


def check_seq_cutoff_parameters(core, seq_cutoff_params):
    current_seq_cutoff_params = core.get_seq_cut_off_parameters()
    failed_params = ""
    if current_seq_cutoff_params.threshold != seq_cutoff_params.threshold:
        failed_params += (
            f"Threshold is {current_seq_cutoff_params.threshold}, "
            f"should be {seq_cutoff_params.threshold}\n"
        )
    if current_seq_cutoff_params.policy != seq_cutoff_params.policy:
        failed_params += (
            f"Policy is {current_seq_cutoff_params.policy}, "
            f"should be {seq_cutoff_params.policy}\n"
        )
    if current_seq_cutoff_params.promotion_count != seq_cutoff_params.promotion_count:
        failed_params += (
            f"Promotion count is {current_seq_cutoff_params.promotion_count}, "
            f"should be {seq_cutoff_params.promotion_count}\n"
        )
    if failed_params:
        TestRun.LOGGER.error(
            f"Sequential cutoff parameters are not correct "
            f"for {core.path}:\n{failed_params}"
        )


def check_cleaning_parameters(cache, cleaning_policy, cleaning_params):
    if cleaning_policy == CleaningPolicy.alru:
        current_cleaning_params = cache.get_flush_parameters_alru()
        failed_params = ""
        if current_cleaning_params.wake_up_time != cleaning_params.wake_up_time:
            failed_params += (
                f"Wake up time is {current_cleaning_params.wake_up_time}, "
                f"should be {cleaning_params.wake_up_time}\n"
            )
        if current_cleaning_params.staleness_time != cleaning_params.staleness_time:
            failed_params += (
                f"Staleness time is {current_cleaning_params.staleness_time}, "
                f"should be {cleaning_params.staleness_time}\n"
            )
        if (
            current_cleaning_params.flush_max_buffers
            != cleaning_params.flush_max_buffers
        ):
            failed_params += (
                f"Flush max buffers is {current_cleaning_params.flush_max_buffers}, "
                f"should be {cleaning_params.flush_max_buffers}\n"
            )
        if (
            current_cleaning_params.activity_threshold
            != cleaning_params.activity_threshold
        ):
            failed_params += (
                f"Activity threshold is {current_cleaning_params.activity_threshold}, "
                f"should be {cleaning_params.activity_threshold}\n"
            )
        if failed_params:
            TestRun.LOGGER.error(
                f"ALRU cleaning policy parameters are not correct "
                f"for cache nr {cache.cache_id}:\n{failed_params}"
            )

    if cleaning_policy == CleaningPolicy.acp:
        current_cleaning_params = cache.get_flush_parameters_acp()
        failed_params = ""
        if current_cleaning_params.wake_up_time != cleaning_params.wake_up_time:
            failed_params += (
                f"Wake up time is {current_cleaning_params.wake_up_time}, "
                f"should be {cleaning_params.wake_up_time}\n"
            )
        if (
            current_cleaning_params.flush_max_buffers
            != cleaning_params.flush_max_buffers
        ):
            failed_params += (
                f"Flush max buffers is {current_cleaning_params.flush_max_buffers}, "
                f"should be {cleaning_params.flush_max_buffers}\n"
            )
        if failed_params:
            TestRun.LOGGER.error(
                f"ACP cleaning policy parameters are not correct "
                f"for cache nr {cache.cache_id}:\n{failed_params}"
            )
