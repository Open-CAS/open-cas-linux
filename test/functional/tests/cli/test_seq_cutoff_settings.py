#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest
import random
from ctypes import c_uint32
from api.cas import casadm
from api.cas.cache_config import SeqCutOffPolicy
from api.cas.core import SEQ_CUTOFF_THRESHOLD_MAX, SEQ_CUT_OFF_THRESHOLD_DEFAULT
from api.cas.casadm import set_param_cutoff_cmd
from core.test_run import TestRun

from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_default_params():
    """
    title: Default sequential cut-off threshold & policy test
    description: Test if proper default threshold and policy is set after cache start
    pass_criteria:
      - "Full" shall be default sequential cut-off policy
      - There shall be default 1MiB (1024kiB) value for sequential cut-off threshold
    """
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()

    with TestRun.step("Getting sequential cut-off parameters"):
        params = cores[0].get_seq_cut_off_parameters()

    with TestRun.step("Check if proper sequential cut off policy is set as a default"):
        if params.policy != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong sequential cut off policy set: {params.policy} "
                         f"should be {SeqCutOffPolicy.DEFAULT}")

    with TestRun.step("Check if proper sequential cut off threshold is set as a default"):
        if params.threshold != SEQ_CUT_OFF_THRESHOLD_DEFAULT:
            TestRun.fail(f"Wrong sequential cut off threshold set: {params.threshold} "
                         f"should be {SEQ_CUT_OFF_THRESHOLD_DEFAULT}")


@pytest.mark.parametrize("policy", SeqCutOffPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_get_policy_core(policy):
    """
    title: Sequential cut-off policy set/get test for core
    description: |
      Test if CAS is setting proper sequential cut-off policy for core and
      returns previously set value
    pass_criteria:
      - Sequential cut-off policy obtained from get-param command for the first core must be
        the same as the one used in set-param command
      - Sequential cut-off policy obtained from get-param command for the second core must be
        proper default value
    """
    with TestRun.step("Test prepare (start cache and add 2 cores)"):
        cache, cores = prepare(cores_count=2)

    with TestRun.step(f"Setting core sequential cut off policy mode to {policy}"):
        cores[0].set_seq_cutoff_policy(policy)

    with TestRun.step("Check if proper sequential cut off policy was set for the first core"):
        if cores[0].get_seq_cut_off_policy() != policy:
            TestRun.fail(f"Wrong sequential cut off policy set: "
                         f"{cores[0].get_seq_cut_off_policy()}  "
                         f"should be {policy}")

    with TestRun.step("Check if proper default sequential cut off policy was set for the "
                      "second core"):
        if cores[1].get_seq_cut_off_policy() != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong default sequential cut off policy: "
                         f"{cores[1].get_seq_cut_off_policy()}  "
                         f"should be {SeqCutOffPolicy.DEFAULT}")


@pytest.mark.parametrize("policy", SeqCutOffPolicy)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_get_policy_cache(policy):
    """
    title: Sequential cut-off policy set/get test for cache
    description: |
      Test if CAS is setting proper sequential cut-off policy for whole cache and
      returns previously set value
    pass_criteria:
      - Sequential cut-off policy obtained from get-param command for each of 3 cores must be the
        same as the one used in set-param command for cache
    """
    with TestRun.step("Test prepare (start cache and add 3 cores)"):
        cache, cores = prepare(cores_count=3)

    with TestRun.step(f"Setting sequential cut off policy mode {policy} for cache"):
        cache.set_seq_cutoff_policy(policy)

    for i in TestRun.iteration(range(0, len(cores)), "Verifying if proper policy was set"):
        with TestRun.step(f"Check if proper sequential cut off policy was set for core"):
            if cores[i].get_seq_cut_off_policy() != policy:
                TestRun.fail(f"Wrong core sequential cut off policy: "
                             f"{cores[i].get_seq_cut_off_policy()} "
                             f"should be {policy}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_policy_load():
    """
    title: Sequential cut-off policy set/get test with cache load between
    description: |
      Set each possible policy for different core, stop cache, test if after cache load
      sequential cut-off policy value previously set is being loaded correctly for each core.
    pass_criteria:
      - Sequential cut-off policy obtained from get-param command after cache load
        must be the same as the one used in set-param command before cache stop
      - Sequential cut-off policy loaded for the last core should be the default one
"""
    with TestRun.step(f"Test prepare (start cache and add {len(SeqCutOffPolicy) + 1} cores)"):
        # Create as many cores as many possible policies including default one
        cache, cores = prepare(cores_count=len(SeqCutOffPolicy) + 1)
        policies = [policy for policy in SeqCutOffPolicy]

    for i, core in TestRun.iteration(enumerate(cores[:-1]), "Set  all possible policies "
                                                            "except the default one"):
        with TestRun.step(f"Setting cache sequential cut off policy mode to "
                          f"{policies[i]}"):
            cores[i].set_seq_cutoff_policy(policies[i])

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step("Loading cache"):
        loaded_cache = casadm.load_cache(cache.cache_device)

    with TestRun.step("Getting cores from loaded cache"):
        cores = loaded_cache.get_core_devices()

    for i, core in TestRun.iteration(enumerate(cores[:-1]), "Check if proper policies have "
                                                            "been loaded"):
        with TestRun.step(f"Check if proper sequential cut off policy was loaded"):
            if cores[i].get_seq_cut_off_policy() != policies[i]:
                TestRun.fail(f"Wrong sequential cut off policy loaded: "
                             f"{cores[i].get_seq_cut_off_policy()} "
                             f"should be {policies[i]}")

    with TestRun.step(f"Check if proper (default) sequential cut off policy was loaded for "
                      f"last core"):
        if cores[len(SeqCutOffPolicy)].get_seq_cut_off_policy() != SeqCutOffPolicy.DEFAULT:
            TestRun.fail(f"Wrong sequential cut off policy loaded: "
                         f"{cores[len(SeqCutOffPolicy)].get_seq_cut_off_policy()} "
                         f"should be {SeqCutOffPolicy.DEFAULT}")


@pytest.mark.parametrize("threshold", random.sample(
    range((int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte)) + 1),
          c_uint32(-1).value), 3))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_set_invalid_threshold(threshold):
    """
    title: Invalid sequential cut-off threshold test
    description: Test if CAS is allowing setting invalid sequential cut-off threshold
    pass_criteria:
      - Setting invalid sequential cut-off threshold should be blocked
    """
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()
        _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step(f"Setting cache sequential cut off threshold to out of range value: "
                      f"{_threshold}"):
        command = set_param_cutoff_cmd(
            cache_id=str(cache.cache_id), core_id=str(cores[0].core_id),
            threshold=str(int(_threshold.get_value())))
        output = TestRun.executor.run_expect_fail(command)
        if "Invalid sequential cutoff threshold, must be in the range 1-4194181"\
                not in output.stderr:
            TestRun.fail("Command succeeded (should fail)!")

    with TestRun.step(f"Setting cache sequential cut off threshold "
                      f"to value passed as a float"):
        command = set_param_cutoff_cmd(
            cache_id=str(cache.cache_id), core_id=str(cores[0].core_id),
            threshold=str(_threshold.get_value()))
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
    title: Sequential cut-off threshold set/get test
    description: |
      Test if CAS is setting proper sequential cut-off threshold and returns
      previously set value
    pass_criteria:
      - Sequential cut-off threshold obtained from get-param command must be the same as
        the one used in set-param command
    """
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()
        _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step(f"Setting cache sequential cut off threshold to "
                      f"{_threshold}"):
        cores[0].set_seq_cutoff_threshold(_threshold)

    with TestRun.step("Check if proper sequential cut off threshold was set"):
        if cores[0].get_seq_cut_off_threshold() != _threshold:
            TestRun.fail(f"Wrong sequential cut off threshold set: "
                         f"{cores[0].get_seq_cut_off_threshold()} "
                         f"should be {_threshold}")


@pytest.mark.parametrize("threshold", random.sample(
    range(1, int(SEQ_CUTOFF_THRESHOLD_MAX.get_value(Unit.KibiByte))), 3))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_seq_cutoff_threshold_load(threshold):
    """
    title: Sequential cut-off threshold set/get test with cache load between
    description: |
      Test if after cache load sequential cut-off threshold
      value previously set is being loaded correctly. Each of possible sequential cut-off
      policies is set for different core.
    pass_criteria:
      - Sequential cut-off threshold obtained from get-param command after cache load
        must be the same as the one used in set-param command before cache stop
    """
    with TestRun.step("Test prepare (start cache and add core)"):
        cache, cores = prepare()
        _threshold = Size(threshold, Unit.KibiByte)

    with TestRun.step(f"Setting cache sequential cut off threshold to "
                      f"{_threshold}"):
        cores[0].set_seq_cutoff_threshold(_threshold)

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step("Loading cache"):
        loaded_cache = casadm.load_cache(cache.cache_device)

    with TestRun.step("Getting core from loaded cache"):
        cores_load = loaded_cache.get_core_devices()

    with TestRun.step("Check if proper sequential cut off policy was loaded"):
        if cores_load[0].get_seq_cut_off_threshold() != _threshold:
            TestRun.fail(f"Wrong sequential cut off threshold set: "
                         f"{cores_load[0].get_seq_cut_off_threshold()} "
                         f"should be {_threshold}")


def prepare(cores_count=1):
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']
    cache_device.create_partitions([Size(500, Unit.MebiByte)])
    partitions = []
    for x in range(cores_count):
        partitions.append(Size(1, Unit.GibiByte))

    core_device.create_partitions(partitions)
    cache_part = cache_device.partitions[0]
    core_parts = core_device.partitions
    TestRun.LOGGER.info("Staring cache")
    cache = casadm.start_cache(cache_part, force=True)
    TestRun.LOGGER.info("Adding core devices")
    core_list = []
    for core_part in core_parts:
        core_list.append(cache.add_core(core_dev=core_part))
    return cache, core_list
