#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, casctl, casadm_parser
from api.cas.casadm_parser import get_caches, get_cores
from api.cas.cache_config import CacheMode
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.filesystem.file import File
from test_tools.disk_utils import Filesystem
from test_utils import fstab
from test_tools.dd import Dd
from test_utils.size import Unit, Size


mountpoint = "/mnt"
filepath = f"{mountpoint}/file"


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_cas_startup(cache_mode, filesystem):
    """
    title: Test for starting CAS on system startup.
    pass_criteria:
      - System does not crash.
      - CAS modules are loaded before partitions are mounted.
      - Cache is loaded before partitions are mounted.
      - Exported object is mounted after startup is complete.
    """
    with TestRun.step("Prepare partitions for cache (200MiB) and for core (400MiB)"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        core = cache.add_core(core_part)

    with TestRun.step("Create and mount filesystem"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(filepath)
            .count(16)
            .block_size(Size(1, Unit.MebiByte))
            .run()
        )
        test_file = File(filepath)
        md5_before = test_file.md5sum()

    with TestRun.step("Add mountpoint fstab and create intelcas.conf"):
        fstab.add_mountpoint(device=core,
                             mount_point=mountpoint,
                             fs_type=filesystem)
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot"):
        TestRun.executor.reboot()

    with TestRun.step("Check if cache is started"):
        caches = list(get_caches())
        if len(caches) != 1:
            TestRun.fail(f"Expected one cache, got {len(caches)}!")
        if caches[0].cache_id != cache.cache_id:
            TestRun.fail("Invalid cache id!")

    with TestRun.step("Check if core is added"):
        cores = list(get_cores(cache.cache_id))
        if len(cores) != 1:
            TestRun.fail(f"Expected one core, got {len(cores)}!")
        if cores[0].core_id != core.core_id:
            TestRun.fail("Invalid core id!")

    with TestRun.step("Check if filesystem is mounted"):
        if not core.is_mounted():
            TestRun.fail("Core is not mounted!")

    with TestRun.step("Check if md5 checksum matches"):
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")

    with TestRun.step("Test cleanup"):
        fstab.remove_mountpoint(device=core)
        core.unmount()
        InitConfig.create_default_init_config()
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode_pair", [(CacheMode.WT, CacheMode.WB),
                                              (CacheMode.WB, CacheMode.WA),
                                              (CacheMode.WA, CacheMode.PT),
                                              (CacheMode.PT, CacheMode.WO),
                                              (CacheMode.WO, CacheMode.WT)])
def test_cas_init_with_changed_mode(cache_mode_pair):
    """
    title: Check starting cache in other cache mode by initializing OpenCAS service from config.
    description: |
      Start cache, create config based on running configuration but with another cache mode,
      reinitialize OpenCAS service with '--force' option and check if cache defined
      in config file starts properly.
      Check all cache modes.
    pass_criteria:
      - Cache starts with attached core
      - Cache starts in mode saved in configuration file.
    """
    with TestRun.step("Prepare partitions for cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step(f"Start cache in the {cache_mode_pair[0]} mode and add core."):
        cache = casadm.start_cache(cache_part, cache_mode_pair[0], force=True)
        core = cache.add_core(core_part)

    with TestRun.step(
            f"Create the configuration file with a different cache mode ({cache_mode_pair[1]})"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(cache.cache_id, cache.cache_device, cache_mode_pair[1])
        init_conf.add_core(cache.cache_id, core.core_id, core.core_device)
        init_conf.save_config_file()

    with TestRun.step("Reinitialize OpenCAS service with '--force' option."):
        casadm.stop_all_caches()
        casctl.init(True)

    with TestRun.step("Check if cache started in correct mode with core attached."):
        validate_cache(cache_mode_pair[1])


@pytest.mark.skip(reason="not implemented")
def test_cas_startup_lazy():
    """
    title: Test successful boot with CAS configuration including lazy_startup
    description: |
      Check that DUT boots succesfully with failing lazy-startup marked devices
    pass_criteria:
      - DUT boots sucesfully
      - caches are configured as expected
    steps:
      - Prepare one drive for caches and one for cores
      - Create 2 cache partitions and 4 core partitons
      - Create opencas.conf config for 2 caches each with 2 core partition as cores
      - Mark first cache as lazy_startup=True
      - Mark first core of second cache as lazy_startup=True
      - Run casctl init
      - Run casctl stop
      - Remove first cache partition
      - Remove first core of second cache partition
      - Reboot DUT
      - Verify DUT booted successfully
      - Verify CAS configured properly
    """
    pass


@pytest.mark.skip(reason="not implemented")
def test_cas_startup_negative_missing_core():
    """
    title: Test unsuccessful boot with CAS configuration
    description: |
      Check that DUT doesn't boot sucesfully when using invalid CAS configuration
    pass_criteria:
      - DUT enters emergency mode
    steps:
      - Prepare one drive for caches and one for cores
      - Create 2 cache partitions and 4 core partitons
      - Create opencas.conf config for 2 caches each with 2 core partitions as cores
      - Mark second cache as lazy_startup=True
      - Run casctl init
      - Run casctl stop
      - Remove second cache cores partitions
      - Reboot DUT
      - Verify the DUT entered emergency mode
    """
    pass


@pytest.mark.skip(reason="not implemented")
def test_cas_startup_negative_missing_cache():
    """
    title: Test unsuccessful boot with CAS configuration
    description: |
      Check that DUT doesn't boot sucesfully when using invalid CAS configuration
    pass_criteria:
      - DUT enters emergency mode
    steps:
      - Prepare one drive for caches and one for cores
      - Create 2 cache partitions and 4 core partitons
      - Create opencas.conf config for 2 caches each with 2 core partitions as cores
      - Mark cores of second cache as lazy_startup=True
      - Run casctl init
      - Run casctl stop
      - Remove second cache partition
      - Reboot DUT
      - Verify the DUT entered emergency mode
    """
    pass


@pytest.mark.skip(reason="not implemented")
def test_failover_config_startup():
    """
    title: Test successful boot with failover-specific configuration options
    description: |
      Check that DUT boots sucesfully and CAS is properly configured when using failover-specific
      configuration options (target_failover_state)
    pass_criteria:
      - DUT boots sucesfully
      - caches are configured as expected
    steps:
      - Prepare two drives for cache and one for core
      - Create opencas.conf config for two caches: one target_failover_state=active with core
      and one target_failover_state=standby
      - Initialize configuration
      - Reboot DUT
      - Wait for successful boot
      - Verify caches state
    """
    pass


@pytest.mark.skip(reason="not implemented")
def test_failover_config_startup_negative():
    """
    title: Test unsuccessful boot with failover-specific configuration options
    description: |
      Check that DUT doesn't boot successfully with misconfigured cache using failover-specific
      configuration options (target_failover_state). After boot it should be verified that emergency
      mode was in fact triggered.
    pass_criteria:
      - DUT enters emergency mode
    steps:
      - Prepare one drive for cache
      - Create partition for cache
      - Create opencas.conf config for single standby cache on created partiton
      - Run casctl init
      - Run casctl stop
      - Remove cache partition
      - Reboot DUT
      - Verify the DUT entered emergency mode
    """
    pass


def validate_cache(cache_mode):
    caches = casadm_parser.get_caches()
    caches_count = len(caches)
    if caches_count != 1:
        TestRun.LOGGER.error(
            f"Cache did not start successfully - wrong number of caches: {caches_count}."
        )

    cores = casadm_parser.get_cores(caches[0].cache_id)
    cores_count = len(cores)
    if cores_count != 1:
        TestRun.LOGGER.error(f"Cache started with wrong number of cores: {cores_count}.")

    current_mode = caches[0].get_cache_mode()
    if current_mode != cache_mode:
        TestRun.LOGGER.error(
            f"Cache started in wrong mode!\n"
            f"Should start in {cache_mode}, but started in {current_mode} mode."
        )
