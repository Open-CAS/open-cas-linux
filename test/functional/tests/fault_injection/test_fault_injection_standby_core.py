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
