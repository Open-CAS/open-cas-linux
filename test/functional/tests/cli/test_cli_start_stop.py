#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from random import randint

from api.cas import casadm, casadm_parser, cli_messages
from api.cas.cli import start_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Unit, Size

CACHE_ID_RANGE = (1, 16384)
CORE_ID_RANGE = (0, 4095)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_start_stop_default_id(shortcut):
    """
        title: Test for starting a cache with a default ID - short and long command
        description: |
          Start a new cache with a default ID and then stop this cache.
        pass_criteria:
          - The cache has successfully started with default ID
          - The cache has successfully stopped
    """
    with TestRun.step("Prepare the device for the cache."):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]

    with TestRun.step("Start the cache."):
        cache = casadm.start_cache(cache_device, shortcut=shortcut, force=True)

    with TestRun.step("Check if the cache has started successfully."):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail(f"There is a wrong number of caches found in the OS: {len(caches)}. "
                         f"Should be only 1.")
        if cache.cache_device.path != cache_device.path:
            TestRun.fail(f"The cache has started using a wrong device:"
                         f" {cache.cache_device.path}."
                         f"\nShould use {cache_device.path}.")

    with TestRun.step("Stop the cache."):
        casadm.stop_cache(cache.cache_id, shortcut=shortcut)

    with TestRun.step("Check if the cache has stopped properly."):
        caches = casadm_parser.get_caches()
        if len(caches) != 0:
            TestRun.fail(f"There is a wrong number of caches found in the OS: {len(caches)}."
                         f"\nNo cache should be present after stopping the cache.")
        output = casadm.list_caches(shortcut=shortcut)
        cli_messages.check_stdout_msg(output, cli_messages.no_caches_running)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_start_stop_custom_id(shortcut):
    """
        title: Test for starting a cache with a custom ID - short and long command
        description: |
          Start a new cache with a random ID (from allowed pool) and then stop this cache.
        pass_criteria:
          - The cache has successfully started with a custom ID
          - The cache has successfully stopped
    """
    with TestRun.step("Prepare the device for the cache."):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]

    with TestRun.step("Start the cache with a random ID."):
        cache_id = randint(*CACHE_ID_RANGE)
        cache = casadm.start_cache(cache_device, cache_id=cache_id, shortcut=shortcut, force=True)
        TestRun.LOGGER.info(f"Cache ID: {cache_id}")

    with TestRun.step("Check if the cache has started successfully."):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail(f"There is a wrong number of caches found in the OS: {len(caches)}. "
                         f"Should be only 1.")
        if cache.cache_device.path != cache_device.path:
            TestRun.fail(f"The cache has started using a wrong device:"
                         f" {cache.cache_device.path}."
                         f"\nShould use {cache_device.path}.")

    with TestRun.step("Stop the cache."):
        casadm.stop_cache(cache.cache_id, shortcut=shortcut)

    with TestRun.step("Check if the cache has stopped properly."):
        caches = casadm_parser.get_caches()
        if len(caches) != 0:
            TestRun.fail(f"There is a wrong number of caches found in the OS: {len(caches)}."
                         f"\nNo cache should be present after stopping the cache.")
        output = casadm.list_caches(shortcut=shortcut)
        cli_messages.check_stdout_msg(output, cli_messages.no_caches_running)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_add_remove_default_id(shortcut):
    """
        title: Test for adding and removing a core with a default ID - short and long command
        description: |
          Start a new cache and add a core to it without passing a core ID as an argument
          and then remove this core from the cache.
        pass_criteria:
          - The core is added to the cache with a default ID
          - The core is successfully removed from the cache
    """
    with TestRun.step("Prepare the devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(50, Unit.MebiByte)])
        cache_device = cache_disk.partitions[0]
        core_device = TestRun.disks['core']

    with TestRun.step("Start the cache and add the core."):
        cache = casadm.start_cache(cache_device, shortcut=shortcut, force=True)
        core = casadm.add_core(cache, core_device, shortcut=shortcut)

    with TestRun.step("Check if the core is added to the cache."):
        caches = casadm_parser.get_caches()
        if len(caches[0].get_core_devices()) != 1:
            TestRun.fail("One core should be present in the cache.")
        if caches[0].get_core_devices()[0].path != core.path:
            TestRun.fail("The core path should be equal to the path of the core added.")

    with TestRun.step("Remove the core from the cache."):
        casadm.remove_core(cache.cache_id, core.core_id, shortcut=shortcut)

    with TestRun.step("Check if the core is successfully removed from still running cache."):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail("One cache should be still present after removing the core.")
        if len(caches[0].get_core_devices()) != 0:
            TestRun.fail("No core device should be present after removing the core.")

    with TestRun.step("Stop the cache."):
        casadm.stop_cache(cache_id=cache.cache_id, shortcut=shortcut)

    with TestRun.step("Check if the cache has successfully stopped."):
        caches = casadm_parser.get_caches()
        if len(caches) != 0:
            TestRun.fail("No cache should be present after stopping the cache.")
        output = casadm.list_caches(shortcut=shortcut)
        cli_messages.check_stdout_msg(output, cli_messages.no_caches_running)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_add_remove_custom_id(shortcut):
    """
        title: Test for adding and removing a core with a custom ID - short and long command
        description: |
          Start a new cache and add a core to it with passing a random core ID
          (from allowed pool) as an argument and then remove this core from the cache.
        pass_criteria:
          - The core is added to the cache with a default ID
          - The core is successfully removed from the cache
    """
    with TestRun.step("Prepare the devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(50, Unit.MebiByte)])
        cache_device = cache_disk.partitions[0]
        core_device = TestRun.disks['core']

    with TestRun.step("Start the cache and add the core with a random ID."):
        core_id = randint(*CORE_ID_RANGE)
        cache = casadm.start_cache(cache_device, shortcut=shortcut, force=True)
        core = casadm.add_core(cache, core_device, core_id=core_id, shortcut=shortcut)
        TestRun.LOGGER.info(f"Core ID: {core_id}")

    with TestRun.step("Check if the core is added to the cache."):
        caches = casadm_parser.get_caches()
        if len(caches[0].get_core_devices()) != 1:
            TestRun.fail("One core should be present in the cache.")
        if caches[0].get_core_devices()[0].path != core.path:
            TestRun.fail("The core path should be equal to the path of the core added.")

    with TestRun.step("Remove the core from the cache."):
        casadm.remove_core(cache.cache_id, core.core_id, shortcut=shortcut)

    with TestRun.step("Check if the core is successfully removed from still running cache."):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail("One cache should be still present after removing the core.")
        if len(caches[0].get_core_devices()) != 0:
            TestRun.fail("No core device should be present after removing the core.")

    with TestRun.step("Stop the cache."):
        casadm.stop_cache(cache_id=cache.cache_id, shortcut=shortcut)

    with TestRun.step("Check if the cache has successfully stopped."):
        caches = casadm_parser.get_caches()
        if len(caches) != 0:
            TestRun.fail("No cache should be present after stopping the cache.")
        output = casadm.list_caches(shortcut=shortcut)
        cli_messages.check_stdout_msg(output, cli_messages.no_caches_running)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_load_and_force(shortcut):
    """
        title: Test if it is possible to use start command with 'load' and 'force' flag at once
        description: |
          Try to start cache with 'load' and 'force' options at the same time
          and check if it is not possible to do
        pass_criteria:
          - Start cache command with both 'force' and 'load' options should fail
          - Proper message should be received
    """
    with TestRun.step("Prepare cache."):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(50, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        cache = casadm.start_cache(cache_device)

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Try to load cache with 'force'."):
        output = TestRun.executor.run(
            start_cmd(cache_dev=cache_device.path, force=True, load=True, shortcut=shortcut)
        )
        if output.exit_code == 0:
            TestRun.fail("Loading cache with 'force' option should fail.")
        cli_messages.check_stderr_msg(output, cli_messages.load_and_force)
