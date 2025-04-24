#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#


import random
from ctypes import c_uint32

import pytest

from api.cas import casadm
from api.cas.cache_config import SeqCutOffPolicy
from api.cas.casadm import set_param_cutoff_cmd
from api.cas.core import SEQ_CUTOFF_THRESHOLD_MAX, SEQ_CUT_OFF_THRESHOLD_DEFAULT
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_default_params():
    """
    title: Default sequential cutoff threshold & policy test
    description: Test if proper default threshold and policy is set after cache start
    pass_criteria:
      - "Full" shall be default sequential cutoff policy
      - There shall be default 1MiB (1024kiB) value for sequential cutoff threshold
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])

        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, force=True)
        core = cache.add_core(core_dev=core_part)

    with TestRun.step("Getting sequential cutoff parameters"):
        params = core.get_seq_cut_off_parameters()

    with TestRun.step("Check if proper sequential cutoff policy is set as a default"):
        if params.policy != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong sequential cutoff policy set: {params.policy} "
                         f"should be {SeqCutOffPolicy.DEFAULT}")

    with TestRun.step("Check if proper sequential cutoff threshold is set as a default"):
        if params.threshold != SEQ_CUT_OFF_THRESHOLD_DEFAULT:
            TestRun.fail(f"Wrong sequential cutoff threshold set: {params.threshold} "
                         f"should be {SEQ_CUT_OFF_THRESHOLD_DEFAULT}")


@pytest.mark.parametrize("policy", SeqCutOffPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_get_policy_core(policy):
    """
    title: Sequential cutoff policy set/get test for core
    description: |
        Verify if it is possible to set and get a sequential cutoff policy per core
    pass_criteria:
      - Sequential cutoff policy obtained from get-param command for the first core must be
        the same as the one used in set-param command
      - Sequential cutoff policy obtained from get-param command for the second core must be
        proper default value
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * 2)

        cache_part = cache_device.partitions[0]

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, force=True)
        cores = [cache.add_core(core_dev=part) for part in core_device.partitions]

    with TestRun.step(f"Setting core sequential cutoff policy mode to {policy}"):
        cores[0].set_seq_cutoff_policy(policy)

    with TestRun.step("Check if proper sequential cutoff policy was set for the first core"):
        if cores[0].get_seq_cut_off_policy() != policy:
            TestRun.fail(f"Wrong sequential cutoff policy set: "
                         f"{cores[0].get_seq_cut_off_policy()}  "
                         f"should be {policy}")

    with TestRun.step("Check if proper default sequential cutoff policy was set for the "
                      "second core"):
        if cores[1].get_seq_cut_off_policy() != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong default sequential cutoff policy: "
                         f"{cores[1].get_seq_cut_off_policy()}  "
                         f"should be {SeqCutOffPolicy.DEFAULT}")


@pytest.mark.parametrize("policy", SeqCutOffPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_get_policy_cache(policy):
    """
    title: Sequential cutoff policy set/get test for cache
    description: |
        Verify if it is possible to set and get a sequential cutoff policy for the whole cache
    pass_criteria:
      - Sequential cutoff policy obtained from get-param command for each of 3 cores must be the
        same as the one used in set-param command for cache
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * 3)

        cache_part = cache_device.partitions[0]

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, force=True)
        cores = [cache.add_core(core_dev=part) for part in core_device.partitions]

    with TestRun.step(f"Setting sequential cutoff policy mode {policy} for cache"):
        cache.set_seq_cutoff_policy(policy)

    for i in TestRun.iteration(range(0, len(cores)), "Verifying if proper policy was set"):
        with TestRun.step(f"Check if proper sequential cutoff policy was set for core"):
            if cores[i].get_seq_cut_off_policy() != policy:
                TestRun.fail(f"Wrong core sequential cutoff policy: "
                             f"{cores[i].get_seq_cut_off_policy()} "
                             f"should be {policy}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_policy_load():
    """
    title: Sequential cutoff policy set/get test with cache load between
    description: |
        Set each possible policy for different core, stop cache, test if after cache load
        sequential cutoff policy value previously set is being loaded correctly for each core.
    pass_criteria:
      - Sequential cutoff policy obtained from get-param command after cache load
        must be the same as the one used in set-param command before cache stop
      - Sequential cutoff policy loaded for the last core should be the default one
    """
    policies = [policy for policy in SeqCutOffPolicy]

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)] * (len(SeqCutOffPolicy) + 1))

        cache_part = cache_device.partitions[0]

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, force=True)
        cores = [cache.add_core(core_dev=part) for part in core_device.partitions]

    for i, core in TestRun.iteration(
            enumerate(cores[:-1]),
            "Set all possible policies except the default one"
    ):
        with TestRun.step(f"Setting cache sequential cutoff policy mode to "
                          f"{policies[i]}"):
            cores[i].set_seq_cutoff_policy(policies[i])

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step("Loading cache"):
        loaded_cache = casadm.load_cache(cache.cache_device)

    with TestRun.step("Getting cores from loaded cache"):
        cores = loaded_cache.get_cores()

    for i, core in TestRun.iteration(
            enumerate(cores[:-1]),
            "Check if proper policies have been loaded"
    ):
        with TestRun.step(f"Check if proper sequential cutoff policy was loaded"):
            if cores[i].get_seq_cut_off_policy() != policies[i]:
                TestRun.fail(f"Wrong sequential cutoff policy loaded: "
                             f"{cores[i].get_seq_cut_off_policy()} "
                             f"should be {policies[i]}")

    with TestRun.step(
            "Check if proper (default) sequential cutoff policy was loaded for last core"
    ):
        if cores[len(SeqCutOffPolicy)].get_seq_cut_off_policy() != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong sequential cutoff policy loaded: "
                         f"{cores[len(SeqCutOffPolicy)].get_seq_cut_off_policy()} "
                         f"should be {SeqCutOffPolicy.DEFAULT}")


@pytest.mark.parametrize("threshold", random.sample(
    range((int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte)) + 1),
          c_uint32(-1).value), 3))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_invalid_threshold(threshold):
    """
    title: Invalid sequential cutoff threshold test
    description: Validate setting invalid sequential cutoff threshold
    pass_criteria:
      - Setting invalid sequential cutoff threshold should be blocked
    """
    _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])

        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, force=True)
        core = cache.add_core(core_dev=core_part)

    with TestRun.step(f"Setting cache sequential cutoff threshold to out of range value: "
                      f"{_threshold}"):
        command = set_param_cutoff_cmd(
            cache_id=str(cache.cache_id), core_id=str(core.core_id),
            threshold=str(int(_threshold.get_value(Unit.KiloByte))))
        output = TestRun.executor.run_expect_fail(command)
        if "Invalid sequential cutoff threshold, must be in the range 1-4194181"\
                not in output.stderr:
            TestRun.fail("Command succeeded (should fail)!")

    with TestRun.step(f"Setting cache sequential cutoff threshold "
                      f"to value passed as a float"):
        command = set_param_cutoff_cmd(
            cache_id=str(cache.cache_id), core_id=str(core.core_id),
            threshold=str(_threshold.get_value(Unit.KiloByte)))
        output = TestRun.executor.run_expect_fail(command)
        if "Invalid sequential cutoff threshold, must be a correct unsigned decimal integer"\
                not in output.stderr:
            TestRun.fail("Command succeeded (should fail)!")


@pytest.mark.parametrize("threshold", random.sample(
    range(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))), 3))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_get_threshold(threshold):
    """
    title: Sequential cutoff threshold set/get test
    description: Verify setting and getting value of sequential cutoff threshold
    pass_criteria:
      - Sequential cutoff threshold obtained from get-param command must be the same as
        the one used in set-param command
    """
    _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])

        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, force=True)
        core = cache.add_core(core_dev=core_part)

    with TestRun.step(f"Setting cache sequential cutoff threshold to "
                      f"{_threshold}"):
        core.set_seq_cutoff_threshold(_threshold)

    with TestRun.step("Check if proper sequential cutoff threshold was set"):
        if core.get_seq_cut_off_threshold() != _threshold:
            TestRun.fail(f"Wrong sequential cutoff threshold set: "
                         f"{core.get_seq_cut_off_threshold()} "
                         f"should be {_threshold}")


@pytest.mark.parametrize("threshold", random.sample(
    range(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))), 3))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_threshold_load(threshold):
    """
    title: Sequential cutoff threshold after loading cache
    description: Verify sequential cutoff threshold value after reloading the cache.
    pass_criteria:
      - Sequential cutoff threshold obtained from get-param command after cache load
        must be the same as the one used in set-param command before cache stop
    """
    _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']

        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])

        cache_part = cache_device.partitions[0]
        core_part = core_device.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, force=True)
        core = cache.add_core(core_dev=core_part)

    with TestRun.step(f"Setting cache sequential cutoff threshold to "
                      f"{_threshold}"):
        core.set_seq_cutoff_threshold(_threshold)

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step("Loading cache"):
        loaded_cache = casadm.load_cache(cache.cache_device)

    with TestRun.step("Getting core from loaded cache"):
        cores_load = loaded_cache.get_cores()

    with TestRun.step("Check if proper sequential cutoff policy was loaded"):
        if cores_load[0].get_seq_cut_off_threshold() != _threshold:
            TestRun.fail(f"Wrong sequential cutoff threshold set: "
                         f"{cores_load[0].get_seq_cut_off_threshold()} "
                         f"should be {_threshold}")
