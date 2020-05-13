#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import pytest

from api.cas import casadm, casadm_parser, cli_messages
from api.cas.cli import start_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Unit, Size


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_start_stop_default_value(shortcut):
    with TestRun.LOGGER.step("Prepare devices"):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]

    with TestRun.LOGGER.step("Start cache"):
        casadm.start_cache(cache_device, shortcut=shortcut, force=True)

    with TestRun.LOGGER.step("Check if cache started successfully"):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.LOGGER.error(f"There is wrong caches count found in OS: {len(caches)}")
        if caches[0].cache_device.system_path != cache_device.system_path:
            TestRun.LOGGER.error(f"Cache started using wrong device: "
                                 f"{caches[0].cache_device.system_path}. "
                                 f"Should be {cache_device.system_path}")

    with TestRun.LOGGER.step("Stop cache"):
        casadm.stop_cache(cache_id=caches[0].cache_id, shortcut=shortcut)

    with TestRun.LOGGER.step("Check if cache stopped properly"):
        output = casadm.list_caches(shortcut=shortcut)
        caches = casadm_parser.get_caches()
        if len(caches) != 0:
            TestRun.LOGGER.error(f"There is wrong caches count found in OS: {len(caches)}. "
                                 f"Should be 0.")
        if output.stdout != "No caches running":
            TestRun.LOGGER.error("There is no 'No caches running' info in casadm -L output")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("shortcut", [True, False])
def test_cli_add_remove_default_value(shortcut):
    cache_device = TestRun.disks['cache']
    cache_device.create_partitions([Size(50, Unit.MebiByte)])
    cache_device = cache_device.partitions[0]
    cache = casadm.start_cache(cache_device, shortcut=shortcut, force=True)

    core_device = TestRun.disks['core']

    casadm.add_core(cache, core_device, shortcut=shortcut)

    caches = casadm_parser.get_caches()
    if len(caches[0].get_core_devices()) != 1:
        TestRun.fail("One core should be present in cache")
    if caches[0].get_core_devices()[0].core_device.system_path != core_device.system_path:
        TestRun.fail("Core path should equal to path of core added")


    casadm.remove_core(cache.cache_id, 1, shortcut=shortcut)
    caches = casadm_parser.get_caches()
    if len(caches) != 1:
        TestRun.fail("One cache should be present still after removing core")
    if len(caches[0].get_core_devices()) != 0:
        TestRun.fail("No core devices should be present after removing core")

    casadm.stop_cache(cache_id=cache.cache_id, shortcut=shortcut)

    output = casadm.list_caches(shortcut=shortcut)
    caches = casadm_parser.get_caches()
    if len(caches) != 0:
        TestRun.fail("No cache should be present after stopping the cache")
    if output.stdout != "No caches running":
        TestRun.fail(f"Invalid message, expected 'No caches running', got {output.stdout}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_cli_load_and_force():
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
            start_cmd(cache_dev=cache_device.system_path, force=True, load=True)
        )
        if output.exit_code == 0:
            TestRun.fail("Loading cache with 'force' option should fail.")
        cli_messages.check_stderr_msg(output, cli_messages.load_and_force)
