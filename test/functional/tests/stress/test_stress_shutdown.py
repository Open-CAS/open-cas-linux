#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
import pytest
from datetime import timedelta
from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheLineSize, CacheMode, CleaningPolicy, CacheModeTrait
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeLowerThan, DiskTypeSet
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.size import Size, Unit

cores_number = 2
iterations_per_config = 5


@pytest.mark.os_dependent
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.require_plugin("power_control")
def test_stress_dirty_shutdown(cache_line_size, cache_mode, cleaning_policy):
    """
        title: Stress test for dirty shutdowns during IO workload.
        description: |
          Validate the ability of CAS to start cache instances upon system boot after
          dirty shutdown during IO workloads.
        pass_criteria:
          - No system crash.
          - CAS loads correctly after DUT hard reset.
    """
    with TestRun.step("Prepare devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(5, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_sizes = [Size(5, Unit.GibiByte)] * cores_number
        core_dev.create_partitions(core_sizes)

    with TestRun.step("Start cache according to configuration and add core devices."):
        cache = casadm.start_cache(cache_part, cache_mode, cache_line_size, force=True)
        if cleaning_policy is not None:
            cache.set_cleaning_policy(cleaning_policy)
        exported_objects = []
        for i in range(0, cores_number):
            exported_objects.append(cache.add_core(core_dev.partitions[i]))

    with TestRun.step("Create CAS init configuration file based on running configuration."):
        InitConfig.create_init_config_from_running_configuration()

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               "Load cache after reboot while heavy IO."):
        with TestRun.step("Start heavy IO workload on both CAS devices."):
            run_io(exported_objects)
            time.sleep(120)

        with TestRun.step("Reset platform."):
            power_control = TestRun.plugin_manager.get_plugin('power_control')
            power_control.power_cycle()

        with TestRun.step("Check configuration after load."):
            check_configuration(cleaning_policy, cache_mode, cache_line_size)

    with TestRun.step("Stop cache."):
        cache.stop()


def check_configuration(cleaning_policy, cache_mode, cache_line_size):
    caches = casadm_parser.get_caches()
    if len(caches) != 1:
        TestRun.fail(f"There is wrong amount of caches running. "
                     f"(Expected: 1, actual: {len(caches)}).")
    actual_cores_number = len(casadm_parser.get_cores(caches[0].cache_id))
    if actual_cores_number != cores_number:
        TestRun.fail(f"There is wrong amount of CAS devices running. (Expected: {cores_number}, "
                     f"actual: {actual_cores_number}).")
    actual_line_size = caches[0].get_cache_line_size()
    actual_cache_mode = caches[0].get_cache_mode()
    actual_cleaning_policy = caches[0].get_cleaning_policy()
    if actual_cleaning_policy != cleaning_policy:
        TestRun.fail(f"Cleaning policy: expected = {cleaning_policy.value}, "
                     f"actual = {actual_cleaning_policy.value}.")
    if actual_cache_mode != cache_mode:
        TestRun.fail(f"Cache mode: expected = {cache_mode.value}, actual = {actual_cache_mode}.")
    if actual_line_size != cache_line_size:
        TestRun.fail(f"Cache line size: expected = {cache_line_size.name}, "
                     f"actual: {actual_line_size.name}")


def run_io(exported_objects):
    for i in range(0, cores_number):
        fio = Fio() \
            .create_command() \
            .read_write(ReadWrite.randrw) \
            .io_engine(IoEngine.libaio) \
            .direct() \
            .sync() \
            .io_depth(32) \
            .run_time(timedelta(minutes=5)) \
            .num_jobs(5) \
            .target(exported_objects[i].path)
        fio.run_in_background()
