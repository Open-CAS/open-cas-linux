#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import time

import pytest

from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode, CacheStatus
from api.cas.core import CoreStatus
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from storage_devices.raid import RaidConfiguration, Raid, Level, MetadataVariant
from test_utils.size import Size, Unit


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.sata]))
def test_udev_core_partition():
    """
        title: |
          CAS udev rule execution after re-attaching partitions existing in configuration file as
          cores.
        description: |
          Verify if CAS udev rule is executed when partitions existing in CAS configuration file
          as cores are being attached.
        pass_criteria:
          - No kernel error
          - Created partitions are added to core pool after attaching core drive.
    """
    cores_count = 4

    with TestRun.step("Create four partitions on core device and one on cache device."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(2, Unit.GibiByte)] * cores_count)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache and add created partitions as cores."):
        cache = casadm.start_cache(cache_dev, force=True)
        for dev in core_devices:
            cache.add_core(dev)

    with TestRun.step("Create init config from running CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Detach core disk."):
        core_disk.unplug()

    with TestRun.step("Plug missing core disk."):
        core_disk.plug()
        time.sleep(1)

    with TestRun.step("List cache devices and check that created partitions are present "
                      "in core pool."):
        for dev in core_devices:
            check_if_dev_in_core_pool(dev)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
def test_udev_core():
    """
        title: CAS udev rule execution for core after detaching and re-attaching cache device.
        description: |
          Verify if CAS udev rule places core in the core pool when cache instance assigned to this
          core is not available in system and attaches core to cache
          when cache is plugged and successfully loaded.
        pass_criteria:
          - No kernel error
          - Core devices are listed in core pool when cache is not available
          - Core devices are moved from core pool and attached to cache after plugging cache device
    """
    with TestRun.step("Start cache and add core."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config from running CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug core disk."):
        core_disk.unplug()

    with TestRun.step("Plug core disk."):
        core_disk.plug()
        time.sleep(1)

    with TestRun.step("Check if core device is listed in core pool."):
        check_if_dev_in_core_pool(core_dev)

    with TestRun.step("Unplug cache disk."):
        cache_disk.unplug()

    with TestRun.step("Plug cache disk."):
        cache_disk.plug()

    with TestRun.step("Check if core device is active and not in the core pool."):
        check_if_dev_in_core_pool(core_dev, False)
        if core.get_status() != CoreStatus.active:
            TestRun.fail(f"Core status is {core.get_status()} instead of active.")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
@pytest.mark.require_disk("core2", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
def test_udev_raid_core():
    """
        title: CAS udev rule execution for core after recreating RAID device existing in
        configuration file as core.
        description: |
          Verify if CAS udev rule is executed for RAID volume recreated after soft reboot.
        pass_criteria:
          - No kernel error
          - After reboot, the RAID volume is added to the cache instance and is in 'active' state
    """
    with TestRun.step("Test prepare."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_disk = core_disk.partitions[0]
        core_disk2 = TestRun.disks["core2"]
        core_disk2.create_partitions([Size(2, Unit.GibiByte)])
        core_disk2 = core_disk2.partitions[0]

    with TestRun.step("Create RAID0 volume."):
        config = RaidConfiguration(
            level=Level.Raid0,
            metadata=MetadataVariant.Legacy,
            number_of_devices=2
        )
        core_dev = Raid.create(config, [core_disk, core_disk2])

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config from running CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot system."):
        TestRun.executor.reboot()

    with TestRun.step("Check if core device is active and not in the core pool."):
        check_if_dev_in_core_pool(core_dev, False)
        if core.get_status() != CoreStatus.active:
            TestRun.fail(f"Core status is {core.get_status()} instead of active.")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_udev_cache_load(cache_mode):
    """
        title: CAS udev rule execution after unplugging and plugging cache device.
        description: |
          Verify if CAS udev rule is executed after unplugging and plugging cache device and if
          cache is properly loaded.
        pass_criteria:
          - No kernel error
          - Cache is properly loaded after plugging cache device
          - Cache is not loaded after unplugging cache device
    """
    with TestRun.step("Start cache."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        cache = casadm.start_cache(cache_dev, cache_mode=cache_mode)

    with TestRun.step("Create init config from running configuration"):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug cache disk."):
        cache_disk.unplug()

    with TestRun.step("Plug cache disk."):
        cache_disk.plug()
        time.sleep(1)

    with TestRun.step("List caches and check if cache is loaded."):
        caches = casadm_parser.get_caches()
        if len(caches) < 1:
            TestRun.fail("Cache did not load.")
        elif len(caches) > 1:
            caches_list = '\n'.join(caches)
            TestRun.fail(f"There is more than 1 cache loaded:\n{caches_list}")
        elif caches[0].cache_device.path != cache_dev.path:
            TestRun.fail(f"Cache loaded on wrong device. "
                         f"Actual: {caches[0].cache_device.path}, "
                         f"expected: {cache_dev.path}")
        elif caches[0].get_cache_mode() != cache_mode:
            TestRun.fail(f"Cache did load with different cache mode. "
                         f"Actual: {caches[0].get_cache_mode()}, expected: {cache_mode}")
        TestRun.LOGGER.info("Cache is correctly loaded.")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.sata, DiskType.hdd]))
def test_neg_udev_cache_load():
    """
        title: CAS udev rule for cache negative test.
        description: |
          Verify if CAS udev rule is executed properly for cache with valid metadata and do not
          load cache with no metadata.
        pass_criteria:
          - No kernel error
          - Cache with metadata is properly loaded
          - Cache without metadata is not loaded
          - Cores assigned to not loaded cache are not inserted to core pool after
            plugging cache disk
          - Cores assigned to not loaded cache are inserted to core pool after plugging core disk
    """
    caches_count = 2
    cores_count = 4

    with TestRun.step("Create init config file with two caches and two cores per each cache."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)] * caches_count)
        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(2, Unit.GibiByte)] * cores_count)
        first_cache_core_numbers = random.sample(range(0, cores_count), 2)
        init_conf = InitConfig()
        for i in range(0, caches_count):
            init_conf.add_cache(i + 1, cache_disk.partitions[i])
        for j in range(0, cores_count):
            init_conf.add_core(1 if j in first_cache_core_numbers else 2,
                               j + 1, core_disk.partitions[j])
        init_conf.save_config_file()

    with TestRun.step("Start one cache and add two cores as defined in init config."):
        cache = casadm.start_cache(cache_disk.partitions[0])
        for i in first_cache_core_numbers:
            cache.add_core(core_disk.partitions[i])

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug and plug cache disk."):
        cache_disk.unplug()
        cache_disk.plug()
        time.sleep(1)

    with TestRun.step("Check if CAS is loaded correctly."):
        cas_devices = casadm_parser.get_cas_devices_dict()
        if len(cas_devices["core_pool"]) != 0:
            TestRun.LOGGER.error(f"There is wrong number of core devices in core pool. Expected: 0,"
                                 f" actual: {len(cas_devices['core_pool'])}")
        if len(cas_devices["caches"]) != 1:
            TestRun.LOGGER.error(f"There is wrong number of caches. Expected: 1, actual: "
                                 f"{len(cas_devices['caches'])}")
        elif cas_devices["caches"][1]["device"] != cache_disk.partitions[0].path or \
                CacheStatus[(cas_devices["caches"][1]["status"]).lower()] != CacheStatus.running:
            TestRun.LOGGER.error(f"Cache did not load properly: {cas_devices['caches'][1]}")
        if len(cas_devices["cores"]) != 2:
            TestRun.LOGGER.error(f"There is wrong number of cores. Expected: 2, actual: "
                                 f"{len(cas_devices['caches'])}")

        correct_core_devices = []
        for i in first_cache_core_numbers:
            correct_core_devices.append(core_disk.partitions[i].path)
        for core in cas_devices["cores"].values():
            if core["device"] not in correct_core_devices or \
                    CoreStatus[core["status"].lower()] != CoreStatus.active or \
                    core["cache_id"] != 1:
                TestRun.LOGGER.error(f"Core did not load correctly: {core}.")

    with TestRun.step("Unplug and plug core disk."):
        core_disk.unplug()
        core_disk.plug()
        time.sleep(1)

    with TestRun.step("Check if two cores assigned to not loaded cache are inserted to core pool."):
        cas_devices = casadm_parser.get_cas_devices_dict()
        if len(cas_devices["core_pool"]) != 2:
            TestRun.LOGGER.error(f"There is wrong number of cores in core pool. Expected: 2, "
                                 f"actual: {len(cas_devices['core_pool'])}")
        core_pool_expected_devices = []
        for i in range(0, cores_count):
            if i not in first_cache_core_numbers:
                core_pool_expected_devices.append(core_disk.partitions[i].path)
        for c in cas_devices["core_pool"]:
            if c["device"] not in core_pool_expected_devices:
                TestRun.LOGGER.error(f"Wrong core device added to core pool: {c}.")


def check_if_dev_in_core_pool(dev, should_be_in_core_pool=True):
    cas_devices_dict = casadm_parser.get_cas_devices_dict()
    is_in_core_pool = any(dev.path == d["device"] for d in cas_devices_dict["core_pool"])
    if not (should_be_in_core_pool ^ is_in_core_pool):
        TestRun.LOGGER.info(f"Core device {dev.path} is"
                            f"{'' if should_be_in_core_pool else ' not'} listed in core pool "
                            f"as expected.")
    else:
        TestRun.fail(f"Core device {dev.path} is{' not' if should_be_in_core_pool else ''} "
                     f"listed in core pool.")
