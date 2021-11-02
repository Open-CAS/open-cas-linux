#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
import pytest

from api.cas import casadm, casctl, casadm_parser, cas_module
from api.cas.cache_config import CacheMode
from api.cas.init_config import InitConfig
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

iterations_per_config = 50
cas_conf_path = "/etc/opencas/opencas.conf"
mount_point = "/mnt/cas"
test_file_path = f"{mount_point}/test_file"


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_load(cache_mode):
    """
        title: Stress test for stopping and loading CAS device.
        description: |
          Validate the ability of the CAS to load and stop cache in the loop
          using different cache modes.
        pass_criteria:
          - No system crash while stop and load cache in the loop.
          - CAS device loads successfully.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev, core_dev = prepare()
    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        casadm.add_core(cache, core_dev)

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Stop cache and load it {iterations_per_config} times."):
        with TestRun.step("Stop cache."):
            casadm.stop_cache(cache.cache_id)
            if len(casadm_parser.get_caches()) != 0:
                TestRun.fail("Cache did not stop successfully.")
        with TestRun.step("Load cache."):
            casadm.load_cache(cache_dev)
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(
                    f"Cache did not load successfully - wrong number of caches: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.LOGGER.error(f"Cache loaded with wrong cores count: {cores_count}.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_service(cache_mode):
    """
        title: Stress test for starting and stopping CAS service.
        description: |
          Validate the ability of CAS to restart CAS service
          and load CAS device in the loop.
        pass_criteria:
          - No system crash while restarting CAS service or loading cache.
          - CAS service restarts with no errors.
          - CAS device loads successfully.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev, core_dev = prepare()
    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        casadm.add_core(cache, core_dev)

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Stop and start CAS service {iterations_per_config} times."):
        with TestRun.step(
                "Create CAS init config based on current running CAS configuration."):
            InitConfig.create_init_config_from_running_configuration()
        with TestRun.step("Stop CAS service."):
            casctl.stop()
        with TestRun.step("Check if service stopped successfully."):
            if len(casadm_parser.get_caches()) != 0:
                TestRun.fail("There are still running caches after stopping service.")
            if len(casadm_parser.get_cores(cache.cache_id)) != 0:
                TestRun.fail("There are still running cores after stopping service.")
        with TestRun.step("Start CAS service."):
            casctl.start()
            time.sleep(1)  # Time for CAS devices to start
        with TestRun.step("Check if CAS configuration loaded successfully."):
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Stop caches and create default init config file."):
        casadm.stop_all_caches()
        InitConfig.create_default_init_config()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_start(cache_mode):
    """
        title: Stress test for starting and stopping cache.
        description: Validate the ability of CAS to start and stop cache in the loop.
        pass_criteria:
          - No system crash while starting and stopping cache in the loop.
          - Cache starts and stops successfully.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev, core_dev = prepare()

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Start and stop CAS {iterations_per_config} times."):
        with TestRun.step("Start cache."):
            cache = casadm.start_cache(cache_dev, cache_mode, force=True)
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
        with TestRun.step("Add core."):
            cache.add_core(core_dev)
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")
        with TestRun.step("Stop cache."):
            cache.stop()
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 0:
                TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_reload_cache(cache_mode):
    """
        title: Stress test for reloading cache with simple data integrity check.
        description: |
          Validate the ability of CAS to reload cache in the loop
          with no data corruption.
        pass_criteria:
          - No system crash while reloading cache.
          - CAS device loads successfully.
          - No data corruption.
    """
    with TestRun.step("Prepare cache and core. Create test file and count its checksum."):
        cache, core, file, file_md5sum_before = prepare_with_file_creation(cache_mode)

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Stop and load cache {iterations_per_config} times."):
        with TestRun.step("Stop cache."):
            cache.stop()
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 0:
                TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")
        with TestRun.step("Load cache."):
            cache = casadm.load_cache(cache.cache_device)
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Check md5 sum of test file."):
        core.mount(mount_point)
        file_md5sum_after = file.md5sum()
        if file_md5sum_after != file_md5sum_before:
            TestRun.LOGGER.error("Md5 sum of test file is different.")
        core.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_add_remove_core(cache_mode):
    """
        title: Stress test for adding and removing core.
        description: Validate the ability of CAS to add and remove core in the loop.
        pass_criteria:
          - No system crash while adding and removing core.
          - Core is added and removed successfully.
          - No data corruption.
    """
    with TestRun.step("Prepare cache and core. Create test file and count its checksum."):
        cache, core, file, file_md5sum_before = prepare_with_file_creation(cache_mode)

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Add and remove core {iterations_per_config} times."):
        with TestRun.step("Remove core."):
            core.remove_core()
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 0:
                TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")
        with TestRun.step("Add core."):
            core = cache.add_core(core.core_device)
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")

    with TestRun.step("Check md5 sum of test file."):
        core.mount(mount_point)
        file_md5sum_after = file.md5sum()
        if file_md5sum_after != file_md5sum_before:
            TestRun.LOGGER.error("Md5 sum of test file is different.")
        core.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stress_reload_module(cache_mode):
    """
        title: Stress test for reloading CAS modules.
        description: Validate the ability of CAS to reload modules in the loop.
        pass_criteria:
          - No system crash while reloading CAS modules.
          - CAS modules reloads with no errors.
          - No data corruption.
    """
    with TestRun.step("Prepare cache and core. Create test file and count its checksum."):
        cache, core, file, file_md5sum_before = prepare_with_file_creation(cache_mode)

    with TestRun.step("Save current cache configuration."):
        cache_config = cache.get_cache_config()

    for _ in TestRun.iteration(range(0, iterations_per_config),
                               f"Reload CAS modules and check loaded "
                               f"cache configuration {iterations_per_config} times."):
        with TestRun.step("Stop cache."):
            cache.stop()
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 0:
                TestRun.fail(f"Expected caches count: 0; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 0:
                TestRun.fail(f"Expected cores count: 0; Actual cores count: {cores_count}.")
        with TestRun.step("Reload CAS modules."):
            cas_module.reload_all_cas_modules()
        with TestRun.step("Load cache."):
            cache = casadm.load_cache(cache.cache_device)
            caches_count = len(casadm_parser.get_caches())
            if caches_count != 1:
                TestRun.fail(f"Expected caches count: 1; Actual caches count: {caches_count}.")
            cores_count = len(casadm_parser.get_cores(cache.cache_id))
            if cores_count != 1:
                TestRun.fail(f"Expected cores count: 1; Actual cores count: {cores_count}.")
        with TestRun.step("Validate cache configuration."):
            if cache.get_cache_config() != cache_config:
                TestRun.fail("Cache configuration is different than before reloading modules.")

    with TestRun.step("Check md5 sum of test file."):
        core.mount(mount_point)
        file_md5sum_after = file.md5sum()
        if file_md5sum_after != file_md5sum_before:
            TestRun.LOGGER.error("Md5 sum of test file is different.")
        core.unmount()

    with TestRun.step("Stop all caches."):
        casadm.stop_all_caches()


def prepare_with_file_creation(config):
    cache_dev, core_dev = prepare()
    cache = casadm.start_cache(cache_dev, config, force=True)
    core = cache.add_core(core_dev)
    core.create_filesystem(Filesystem.ext3)
    core.mount(mount_point)
    file = fs_utils.create_random_test_file(test_file_path)
    file_md5sum = file.md5sum()
    core.unmount()
    return cache, core, file, file_md5sum


def prepare():
    cache_dev = TestRun.disks['cache']
    cache_dev.create_partitions([Size(2, Unit.GibiByte)])
    core_dev = TestRun.disks['core']
    core_dev.create_partitions([Size(1, Unit.GibiByte)])
    return cache_dev.partitions[0], core_dev.partitions[0]
