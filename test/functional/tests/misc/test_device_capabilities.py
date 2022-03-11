#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import math
import pytest
import os
from api.cas import casadm, cli_messages
from api.cas.cache_config import CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from storage_devices.partition import Partition
from test_tools import disk_utils, fs_utils
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.nand]))
@pytest.mark.require_plugin("scsi_debug")
def test_device_capabilities():
    """
        title: Test whether CAS device capabilities are properly set.
        description: |
          Test if CAS device takes into consideration differences between devices which are used to
          create it.
        pass_criteria:
          - CAS device starts successfully using differently configured devices.
          - CAS device capabilities are as expected.
    """

    core_device = TestRun.disks['core']
    max_io_size_path = os.path.join(disk_utils.get_sysfs_path(core_device.get_device_id()),
                                    'queue/max_sectors_kb')
    default_max_io_size = fs_utils.read_file(max_io_size_path)

    iteration_settings = [
        {"device": "SCSI-debug module",
         "dev_size_mb": 1024, "logical_block_size": 512, "max_sectors_kb": 1024},
        {"device": "SCSI-debug module",
         "dev_size_mb": 1024, "logical_block_size": 512, "max_sectors_kb": 256},
        {"device": "SCSI-debug module",
         "dev_size_mb": 1024, "logical_block_size": 512, "max_sectors_kb": 128},
        {"device": "SCSI-debug module",
         "dev_size_mb": 2048, "logical_block_size": 2048, "max_sectors_kb": 1024},
        {"device": "standard core device",
         "max_sectors_kb": int(default_max_io_size)},
        {"device": "standard core device", "max_sectors_kb": 128}
    ]

    for i in range(0, len(iteration_settings)):
        device = iteration_settings[i]["device"]
        group_title = f"{device} | "
        if device == "SCSI-debug module":
            group_title += f"dev_size_mb = {iteration_settings[i]['dev_size_mb']} | " \
                           f"logical_block_size = {iteration_settings[i]['logical_block_size']} | "
        group_title += f"max_sectors_kb = {iteration_settings[i]['max_sectors_kb']}"

        with TestRun.group(group_title):
            with TestRun.step("Prepare devices."):
                core_device = prepare_core_device(iteration_settings[i])
                cache_device = TestRun.disks['cache']

            with TestRun.step("Start cache and add prepared core device as core."):
                cache, core, error_output = prepare_cas_device(cache_device, core_device)
            with TestRun.step("Compare capabilities for CAS device, cache and core "
                              "(or check proper error if logical sector mismatch occurs)."):
                compare_capabilities(cache_device, core_device, cache, core, error_output)
            with TestRun.step("Recreate CAS device with switched cache and core devices."):
                cache, core, error_output = prepare_cas_device(core_device, cache_device)
            with TestRun.step("Compare capabilities for CAS device, cache and core "
                              "(or check proper error if logical sector mismatch occurs)."):
                compare_capabilities(core_device, cache_device, cache, core, error_output)


# Methods used in test

def prepare_core_device(settings):
    if settings["device"] == "SCSI-debug module":
        core_device = create_scsi_debug_device(
            settings["logical_block_size"], 4, settings["dev_size_mb"])
    else:
        core_device = TestRun.disks['core']
    core_device.set_max_io_size(Size(settings["max_sectors_kb"], Unit.KibiByte))
    return core_device


def create_scsi_debug_device(sector_size: int, physblk_exp: int, dev_size_mb=1024):
    scsi_debug_params = {
        "delay": "0",
        "virtual_gb": "200",
        "dev_size_mb": str(dev_size_mb),
        "sector_size": str(sector_size),
        "physblk_exp": str(physblk_exp)
    }
    scsi_debug = TestRun.plugin_manager.get_plugin('scsi_debug')
    scsi_debug.params = scsi_debug_params
    scsi_debug.reload()
    return TestRun.scsi_debug_devices[0]


def prepare_cas_device(cache_device, core_device):
    cache = casadm.start_cache(cache_device, cache_line_size=CacheLineSize.LINE_64KiB, force=True)
    try:
        cache_dev_bs = disk_utils.get_block_size(cache_device.get_device_id())
        core_dev_bs = disk_utils.get_block_size(core_device.get_device_id())
        core = cache.add_core(core_device)
        if cache_dev_bs > core_dev_bs:
            TestRun.LOGGER.error(
                f"CAS device started with cache device logical block size ({cache_dev_bs}) "
                f"greater than core device logical block size ({core_dev_bs})")
        return cache, core, None
    except CmdException as e:
        if cache_dev_bs <= core_dev_bs:
            TestRun.fail("Failed to create CAS device.")
        TestRun.LOGGER.info("Cannot add core device with mismatching logical sector size. "
                            "Check output instead of capabilities.")
        return cache, None, e.output


def method_min_not_zero(a, b):
    return a if a != 0 and (a < b or b == 0) else b


def method_lcm_not_zero(a, b):
    if a == 0 or b == 0:
        return max([a, b])
    # gcd - greatest common divisor
    return a * b / math.gcd(a, b)


# device capabilities and their test comparison methods
capabilities = {"logical_block_size": max,
                "max_hw_sectors_kb": None,
                "max_integrity_segments": method_min_not_zero,
                "max_sectors_kb": None,
                "max_segments": None,
                "minimum_io_size": max,
                "optimal_io_size": method_lcm_not_zero,
                "physical_block_size": max,
                "write_same_max_bytes": min}


def measure_capabilities(dev):
    dev_capabilities = {}
    dev_id = dev.parent_device.get_device_id() if isinstance(dev, Partition) \
        else dev.get_device_id()
    for c in capabilities:
        path = os.path.join(disk_utils.get_sysfs_path(dev_id), 'queue', c)
        command = f"cat {path}"
        output = TestRun.executor.run(command)
        if output.exit_code == 0:
            val = int(output.stdout)
            dev_capabilities.update({c: val})
        else:
            TestRun.LOGGER.info(f"Could not measure capability: {c} for {dev_id}")
    return dev_capabilities


def compare_capabilities(cache_device, core_device, cache, core, msg):
    if core is None:
        cli_messages.check_stderr_msg(msg,
                                      cli_messages.try_add_core_sector_size_mismatch)
    else:
        core_dev_sectors_num = \
            disk_utils.get_size(core_device.get_device_id()) / disk_utils.get_block_size(
                core_device.get_device_id())
        core_sectors_num = disk_utils.get_size(core.get_device_id()) / disk_utils.get_block_size(
            core.get_device_id())
        if core_dev_sectors_num != core_sectors_num:
            TestRun.LOGGER.error(
                "Number of sectors in CAS device and attached core device is different.")
            cache.stop()
            return
        cas_capabilities = measure_capabilities(core)
        cache_dev_capabilities = measure_capabilities(cache_device)
        core_dev_capabilities = measure_capabilities(core_device)

        for (capability, method) in capabilities.items():
            cas_val = cas_capabilities[capability]
            cache_val = cache_dev_capabilities[capability]
            core_val = core_dev_capabilities[capability]

            expected_val = method(core_val, cache_val) if method is not None else core_val

            if capability in ["max_sectors_kb", "max_hw_sectors_kb"] and expected_val != cas_val:
                # On the newer kernels this trait is rounded. Instead of checking for
                # the current kernel version, assume that both values are acceptable.
                SECTOR_SHIFT = 9
                lbs = measure_capabilities(core)["logical_block_size"]
                # The original uint is kb, but number of sectors is needed
                new_expected_val = expected_val * 2
                round_val = lbs >> SECTOR_SHIFT
                new_expected_val -= new_expected_val % round_val
                # Restore the original unit
                expected_val = new_expected_val // 2

            if expected_val != cas_val:
                TestRun.LOGGER.error(f"Cas device {capability} is not set properly. Is: {cas_val}, "
                                     f"should be {expected_val} (cache: {cache_val}, "
                                     f"core: {core_val})")
                continue
            TestRun.LOGGER.info(f"Cas device {capability} has proper value: {cas_val} "
                                f"(cache: {cache_val}, core: {core_val})")
    cache.stop()
