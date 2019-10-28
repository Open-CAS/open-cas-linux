#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


import pytest
from api.cas import casadm, casadm_parser
from core.test_run import TestRun
from storage_devices.disk import DiskType
from test_utils.size import Unit, Size


@pytest.mark.parametrize("shortcut", [True, False])
@pytest.mark.parametrize('prepare_and_cleanup',
                         [{"core_count": 0, "cache_count": 1, "cache_type": "optane"}, ],
                         indirect=True)
def test_cli_start_stop_default_value(prepare_and_cleanup, shortcut):
    with TestRun.LOGGER.step("Prepare devices"):
        cache_device = next(
            disk for disk in TestRun.dut.disks if disk.disk_type == DiskType.optane)
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


@pytest.mark.parametrize("shortcut", [True, False])
@pytest.mark.parametrize('prepare_and_cleanup',
                         [{"core_count": 1, "cache_count": 1, "cache_type": "optane"}],
                         indirect=True)
def test_cli_add_remove_default_value(prepare_and_cleanup, shortcut):
    cache_device = next(
        disk for disk in TestRun.dut.disks if disk.disk_type == DiskType.optane)
    cache_device.create_partitions([Size(500, Unit.MebiByte)])
    cache_device = cache_device.partitions[0]
    cache = casadm.start_cache(cache_device, shortcut=shortcut, force=True)

    core_device = next(
        disk for disk in TestRun.dut.disks if disk.disk_type != DiskType.optane)
    casadm.add_core(cache, core_device, shortcut=shortcut)

    caches = casadm_parser.get_caches()
    assert len(caches[0].get_core_devices()) == 1
    assert caches[0].get_core_devices()[0].core_device.system_path == core_device.system_path

    casadm.remove_core(cache.cache_id, 1, shortcut=shortcut)
    caches = casadm_parser.get_caches()
    assert len(caches) == 1
    assert len(caches[0].get_core_devices()) == 0

    casadm.stop_cache(cache_id=cache.cache_id, shortcut=shortcut)

    output = casadm.list_caches(shortcut=shortcut)
    caches = casadm_parser.get_caches()
    assert len(caches) == 0
    assert output.stdout == "No caches running"
