#
# Copyright(c) 2020-2021 Intel Corporation
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
from test_utils.size import Size, Unit


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
def test_set_get_seqcutoff_params(cache_mode):
    """
        title: Test for setting and reading sequential cut-off parameters.
        description: |
          Verify that it is possible to set and read all available sequential cut-off
          parameters using casadm --set-param and --get-param options.
        pass_criteria:
          - All sequential cut-off parameters are set to given values.
          - All sequential cut-off parameters displays proper values.
    """

    with TestRun.step("Partition cache and core devices"):
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches in {cache_mode} cache mode "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_mode, cache_dev, core_dev)

    with TestRun.step("Check sequential cut-off default parameters"):
        default_seqcutoff_params = SeqCutOffParameters.default_seq_cut_off_params()
        for i in range(caches_count):
            for j in range(cores_per_cache):
                check_seqcutoff_parameters(cores[i][j], default_seqcutoff_params)

    with TestRun.step(
        "Set new random values for sequential cut-off parameters for one core only"
    ):
        for check in range(number_of_checks):
            random_seqcutoff_params = new_seqcutoff_parameters_random_values()
            cores[0][0].set_seq_cutoff_parameters(random_seqcutoff_params)

            # Check changed parameters for first core:
            check_seqcutoff_parameters(cores[0][0], random_seqcutoff_params)

            # Check default parameters for other cores:
            for j in range(1, cores_per_cache):
                check_seqcutoff_parameters(cores[0][j], default_seqcutoff_params)
            for i in range(1, caches_count):
                for j in range(cores_per_cache):
                    check_seqcutoff_parameters(cores[i][j], default_seqcutoff_params)

    with TestRun.step(
        "Set new random values for sequential cut-off parameters "
        "for all cores within given cache instance"
    ):
        for check in range(number_of_checks):
            random_seqcutoff_params = new_seqcutoff_parameters_random_values()
            caches[0].set_seq_cutoff_parameters(random_seqcutoff_params)

            # Check changed parameters for first cache instance:
            for j in range(cores_per_cache):
                check_seqcutoff_parameters(cores[0][j], random_seqcutoff_params)

            # Check default parameters for other cache instances:
            for i in range(1, caches_count):
                for j in range(cores_per_cache):
                    check_seqcutoff_parameters(cores[i][j], default_seqcutoff_params)

    with TestRun.step(
        "Set new random values for sequential cut-off parameters for all cores"
    ):
        for check in range(number_of_checks):
            seqcutoff_params = []
            for i in range(caches_count):
                for j in range(cores_per_cache):
                    random_seqcutoff_params = new_seqcutoff_parameters_random_values()
                    seqcutoff_params.append(random_seqcutoff_params)
                    cores[i][j].set_seq_cutoff_parameters(random_seqcutoff_params)
            for i in range(caches_count):
                for j in range(cores_per_cache):
                    check_seqcutoff_parameters(
                        cores[i][j], seqcutoff_params[i * cores_per_cache + j]
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
        cache_dev, core_dev = storage_prepare()

    with TestRun.step(
        f"Start {caches_count} caches in {cache_mode} cache mode "
        f"and add {cores_per_cache} cores per cache"
    ):
        caches, cores = cache_prepare(cache_mode, cache_dev, core_dev)

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


def storage_prepare():
    cache_dev = TestRun.disks["cache"]
    cache_parts = [Size(1, Unit.GibiByte)] * caches_count
    cache_dev.create_partitions(cache_parts)
    core_dev = TestRun.disks["core"]
    core_parts = [Size(2, Unit.GibiByte)] * cores_per_cache * caches_count
    core_dev.create_partitions(core_parts)

    return cache_dev, core_dev


def cache_prepare(cache_mode, cache_dev, core_dev):
    caches = []
    for i in range(caches_count):
        caches.append(
            casadm.start_cache(cache_dev.partitions[i], cache_mode, force=True)
        )
    cores = [[] for i in range(caches_count)]
    for i in range(caches_count):
        for j in range(cores_per_cache):
            core_partition_nr = i * cores_per_cache + j
            cores[i].append(caches[i].add_core(core_dev.partitions[core_partition_nr]))

    return caches, cores


def new_seqcutoff_parameters_random_values():
    return SeqCutOffParameters(
        threshold=Size(random.randrange(1, 1000000), Unit.KibiByte),
        policy=random.choice(list(SeqCutOffPolicy)),
        promotion_count=random.randrange(1, 65535)
    )


def new_cleaning_parameters_random_values(cleaning_policy):
    if cleaning_policy == CleaningPolicy.alru:
        alru_params_range = FlushParametersAlru().alru_params_range()
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
        cleaning_params = FlushParametersAlru()
        cleaning_params.wake_up_time = wake_up_time_random_value
        cleaning_params.staleness_time = staleness_time_random_value
        cleaning_params.flush_max_buffers = flush_max_buffers_random_value
        cleaning_params.activity_threshold = activity_threshold_random_value

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


def check_seqcutoff_parameters(core, seqcutoff_params):
    current_seqcutoff_params = core.get_seq_cut_off_parameters()
    failed_params = ""
    if current_seqcutoff_params.threshold != seqcutoff_params.threshold:
        failed_params += (
            f"Threshold is {current_seqcutoff_params.threshold}, "
            f"should be {seqcutoff_params.threshold}\n"
        )
    if current_seqcutoff_params.policy != seqcutoff_params.policy:
        failed_params += (
            f"Policy is {current_seqcutoff_params.policy}, "
            f"should be {seqcutoff_params.policy}\n"
        )
    if current_seqcutoff_params.promotion_count != seqcutoff_params.promotion_count:
        failed_params += (
            f"Promotion count is {current_seqcutoff_params.promotion_count}, "
            f"should be {seqcutoff_params.promotion_count}\n"
        )
    if failed_params:
        TestRun.LOGGER.error(
            f"Sequential cut-off parameters are not correct "
            f"for {core.path}:\n{failed_params}"
        )


def check_cleaning_parameters(cache, cleaning_policy, cleaning_params):
    if cleaning_policy == CleaningPolicy.alru:
        current_cleaning_params = cache.get_flush_parameters_alru()
        failed_params = ""
        if current_cleaning_params.wake_up_time != cleaning_params.wake_up_time:
            failed_params += (
                f"Wake Up time is {current_cleaning_params.wake_up_time}, "
                f"should be {cleaning_params.wake_up_time}\n"
            )
        if current_cleaning_params.staleness_time != cleaning_params.staleness_time:
            failed_params += (
                f"Staleness Time is {current_cleaning_params.staleness_time}, "
                f"should be {cleaning_params.staleness_time}\n"
            )
        if (
            current_cleaning_params.flush_max_buffers
            != cleaning_params.flush_max_buffers
        ):
            failed_params += (
                f"Flush Max Buffers is {current_cleaning_params.flush_max_buffers}, "
                f"should be {cleaning_params.flush_max_buffers}\n"
            )
        if (
            current_cleaning_params.activity_threshold
            != cleaning_params.activity_threshold
        ):
            failed_params += (
                f"Activity Threshold is {current_cleaning_params.activity_threshold}, "
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
                f"Wake Up time is {current_cleaning_params.wake_up_time}, "
                f"should be {cleaning_params.wake_up_time}\n"
            )
        if (
            current_cleaning_params.flush_max_buffers
            != cleaning_params.flush_max_buffers
        ):
            failed_params += (
                f"Flush Max Buffers is {current_cleaning_params.flush_max_buffers}, "
                f"should be {cleaning_params.flush_max_buffers}\n"
            )
        if failed_params:
            TestRun.LOGGER.error(
                f"ACP cleaning policy parameters are not correct "
                f"for cache nr {cache.cache_id}:\n{failed_params}"
            )
