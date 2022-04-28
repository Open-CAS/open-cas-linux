#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import cli, casadm
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from core.test_run import TestRun
from test_utils.size import Size, Unit
from api.cas.cache_config import CacheLineSize, CacheMode, CacheStatus
from api.cas.casadm_params import StatsFilter
from api.cas.casadm_parser import get_core_info_by_path
from api.cas.core import CoreStatus, Core
from test_tools.dd import Dd
from api.cas.cli import standby_activate_cmd
from api.cas.cli_messages import (
    check_stderr_msg,
    check_stdout_msg,
    activate_with_different_cache_id,
    load_inactive_core_missing,
    cache_activated_successfully,
    invalid_core_volume_size,
    error_activating_cache,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_activate_neg_cache_id():
    """
    title: Blocking cache with mismatching cache ID activation
    description: |
      Try restoring cache operations from a replicated cache that was initialized
      with different cache ID than the original cache
    pass_criteria:
      - The activation is cancelled
      - The cache remains in Standby detached state after an unsuccessful activation
      - The cache exported object is present after an unsuccessful activation
      - A proper error message is displayed
    """
    with TestRun.step("Prepare two partitions of the same size"):
        disk = TestRun.disks["cache"]
        disk.create_partitions([Size(200, Unit.MebiByte), Size(200, Unit.MebiByte)])
        active_dev = disk.partitions[0]
        standby_dev = disk.partitions[1]

    with TestRun.step(
        "Start a regular cache instance explicitly providing a valid cache id and stop it"
    ):
        active_cache_id = 5
        standby_cache_id = 15
        cache_exp_obj_name = f"cas-cache-{standby_cache_id}"
        cls = CacheLineSize.LINE_32KiB
        cache = casadm.start_cache(
            active_dev, cache_id=active_cache_id, cache_line_size=cls, force=True
        )
        cache.stop()

    with TestRun.step(
        "On the second partition initialize standby instance with different cache id"
    ):
        standby_cache = casadm.standby_init(
            standby_dev,
            cache_line_size=int(cls.value.value / Unit.KibiByte.value),
            cache_id=standby_cache_id,
            force=True,
        )

    with TestRun.step("Copy contents of the first partition into the cache exported object"):
        Dd().input(active_dev.path).output(f"/dev/{cache_exp_obj_name}").run()

    with TestRun.step("Verify if the cache exported object appeared in the system"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep {cache_exp_obj_name}")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")

    with TestRun.step("Detach the standby instance"):
        standby_cache.standby_detach()

    with TestRun.step("Try to activate the standby cache instance with different cache id"):
        output = TestRun.executor.run_expect_fail(
            standby_activate_cmd(cache_dev=standby_dev.path, cache_id=str(standby_cache_id))
        )
        if not check_stderr_msg(output, activate_with_different_cache_id):
            TestRun.LOGGER.error(
                f"Invalid error message. Expected {activate_with_different_cache_id}."
                f"Got {output.stderr}"
            )

        status = standby_cache.get_status()
        if status != CacheStatus.standby_detached:
            TestRun.LOGGER.error(
                "The standby cache instance is in an invalid state "
                f"Expected {CacheStatus.standby_detached}. Got {status}"
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_activate_incomplete_cache():
    """
    title: Activating cache with a missing core device.
    description: |
      Try restoring cache operations from a standby cache when the core device
      used before is missing.
    pass_criteria:
      -The activation succeedes when the required core device is missing
      -The cache is transitioned into Incomplete state after a successful activation
      -The message about activating into “Incomplete” state is displayed
      -The cache instance is switched into “Running” mode when the core device appears
       in the system
    """
    with TestRun.step("Prepare partitions"):
        core_part_size = Size(200, Unit.MebiByte)
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)])
        core_disk.create_partitions([core_part_size])
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]
        core_dev_path = core_dev.path

    with TestRun.step("Start a regular cache instance with a core"):
        cache = casadm.start_cache(cache_dev, force=True)
        cache.add_core(core_dev)

    with TestRun.step("Stop the cache device"):
        cache.stop()

    with TestRun.step("Remove the partition used as core"):
        core_disk.remove_partitions()
        core_dev = None

    with TestRun.step("Load standby cache instance"):
        cache = casadm.standby_load(cache_dev)

    with TestRun.step("Verify if the cache exported object appeared in the system"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep cas-cache-1")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")

    with TestRun.step("Detach the standby instance"):
        cache.standby_detach()

    with TestRun.step("Activate standby cache and check if a proper incompleteness info appeared"):
        output = cache.standby_activate(device=cache_dev)
        check_stderr_msg(output, load_inactive_core_missing)
        check_stdout_msg(output, cache_activated_successfully)

    with TestRun.step("Verify that the cache is in Incomplete state"):
        status = cache.get_status()
        if status != CacheStatus.incomplete:
            TestRun.LOGGER.error(
                "The cache instance is in an invalid state. "
                f"Expected {CacheStatus.incomplete}. Got {status}"
            )

    with TestRun.step("Check if the number of cores is valid"):
        cache_conf_stats = cache.get_statistics(stat_filter=[StatsFilter.conf])
        core_count = int(cache_conf_stats.config_stats.core_dev)
        if core_count != 1:
            TestRun.fail(f"Expected one core. Got {core_count}")

    with TestRun.step("Check if the number of inactive cores is valid"):
        inactive_core_count = int(cache_conf_stats.config_stats.inactive_core_dev)
        if inactive_core_count != 1:
            TestRun.fail(f"Expected one inactive core. Got {inactive_core_count}")

    with TestRun.step("Check if core is in an appropriate state"):
        core_status = CoreStatus[get_core_info_by_path(core_dev_path)["status"].lower()]
        if core_status != CoreStatus.inactive:
            TestRun.fail(
                "The core is in an invalid state. "
                f"Expected {CoreStatus.inactive}. Got {core_status}"
            )

    with TestRun.step("Restore core partition"):
        core_disk.create_partitions([core_part_size])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Add core using try-add script command"):
        casadm.try_add(core_dev, cache_id=1, core_id=1)

    with TestRun.step("Verify that the cache is in Running state"):
        status = cache.get_status()
        if status != CacheStatus.running:
            TestRun.LOGGER.error(
                "The cache instance is in an invalid state. "
                f"Expected {CacheStatus.running}. Got {status}"
            )

    with TestRun.step("Verify that the core is in Active state"):
        cache_conf_stats = cache.get_statistics(stat_filter=[StatsFilter.conf])
        core_count = int(cache_conf_stats.config_stats.core_dev)
        if core_count != 1:
            TestRun.fail(f"Expected one core. Got {core_count}")

    with TestRun.step("Check if the number of inactive cores is valid"):
        inactive_core_count = int(cache_conf_stats.config_stats.inactive_core_dev)
        if inactive_core_count != 0:
            TestRun.fail(
                f"The test didn't expect inactive cores at this point. "
                f"Got {inactive_core_count}"
            )

        core_status = Core(core_device=core_dev.path, cache_id=1).get_status()
        if core_status != CoreStatus.active:
            TestRun.LOGGER.error(
                "The core is in an invalid state. "
                f"Expected {CoreStatus.active}. Got {core_status}"
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_activate_neg_core_size():
    """
    title: Activating cache with a core of a altered size.
    description: |
      Try restoring cache operations from a standby cache when the core device size has been altered
    pass_criteria:
      - The cache activation is cancelled when a core device size mismatch occurs
      - The cache remains in standby detached state after an unsuccessful activation
      - A proper error message is displayed
    """
    with TestRun.step("Prepare partitions"):
        core_part_size = Size(200, Unit.MebiByte)
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)])
        core_disk.create_partitions([core_part_size])
        cache_dev = cache_disk.partitions[0]
        core_dev = core_disk.partitions[0]
        core_dev_path = core_dev.path

    with TestRun.step("Start a regular cache instance with a core"):
        cache = casadm.start_cache(cache_dev, force=True)
        cache.add_core(core_dev)

    with TestRun.step("Stop the cache device"):
        cache.stop()

    with TestRun.step("Resize the partition used as core"):
        core_disk.remove_partitions()
        core_disk.create_partitions([Size(400, Unit.MebiByte)])

    with TestRun.step("Load standby cache instance"):
        cache = casadm.standby_load(cache_dev)

    with TestRun.step("Verify if the cache exported object appeared in the system"):
        output = TestRun.executor.run_expect_success(f"ls -la /dev/ | grep cas-cache-1")
        if output.stdout[0] != "b":
            TestRun.fail("The cache exported object is not a block device")

    with TestRun.step("Detach the standby instance"):
        cache.standby_detach()

    with TestRun.step("Try if activate fails and returns the same error every time"):
        activate_cmd = standby_activate_cmd(cache_dev=cache_dev.path, cache_id="1")
        for i in range(10):
            output = TestRun.executor.run_expect_fail(activate_cmd)
            check_stderr_msg(output, error_activating_cache)
            check_stderr_msg(output, invalid_core_volume_size)

    with TestRun.step("Verify that the cache is in Standby detached state"):
        status = cache.get_status()
        if status != CacheStatus.standby_detached:
            TestRun.LOGGER.error(
                "The cache instance is in an invalid state. "
                f"Expected {CacheStatus.standby_detached}. Got {status}"
            )

    with TestRun.step("Restore the original size of core partition"):
        core_disk.remove_partitions()
        core_disk.create_partitions([core_part_size])
        core_dev = core_disk.partitions[0]

    with TestRun.step("Activate standby cache"):
        output = cache.standby_activate(device=cache_dev)
        check_stdout_msg(output, cache_activated_successfully)

    with TestRun.step("Verify that the cache is in Running state"):
        status = cache.get_status()
        if status != CacheStatus.running:
            TestRun.LOGGER.error(
                "The cache instance is in an invalid state. "
                f"Expected {CacheStatus.running}. Got {status}"
            )

    with TestRun.step("Verify that the core is in Active state"):
        core_status = Core(core_device=core_dev.path, cache_id=1).get_status()
        if core_status != CoreStatus.active:
            TestRun.LOGGER.error(
                "The core is in an invalid state. "
                f"Expected {CoreStatus.active}. Got {core_status}"
            )

    with TestRun.step("Check if the number of active cores is valid"):
        cache_conf_stats = cache.get_statistics(stat_filter=[StatsFilter.conf])
        core_count = int(cache_conf_stats.config_stats.core_dev)
        if core_count != 1:
            TestRun.fail(f"Expected one core. Got {core_count}")

    with TestRun.step("Check if the number of inactive cores is valid"):
        inactive_core_count = int(cache_conf_stats.config_stats.inactive_core_dev)
        if inactive_core_count != 0:
            TestRun.fail(
                f"The test didn't expect inactive cores at this point. "
                f"Got {inactive_core_count}"
            )
