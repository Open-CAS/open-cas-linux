#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import pytest

from api.cas import casadm, ioclass_config
from api.cas.cache_config import CacheMode
from api.cas.casadm_params import OutputFormat
from api.cas.ioclass_config import IoClass
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_utils.size import Size, Unit

ioclass_config_path = "/tmp/opencas_ioclass.conf"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_ioclass_export_configuration(cache_mode):
    """
    title: Export IO class configuration to a file
    description: |
        Test CAS ability to create a properly formatted file with current IO class configuration
    pass_criteria:
     - CAS default IO class configuration contains unclassified class only
     - CAS properly imports previously exported configuration
    """
    with TestRun.LOGGER.step(f"Test prepare"):
        cache, core = prepare(cache_mode)
        saved_config_path = "/tmp/opencas_saved.conf"
        default_list = [IoClass.default()]

    with TestRun.LOGGER.step(f"Check IO class configuration (should contain only default class)"):
        csv = casadm.list_io_classes(cache.cache_id, OutputFormat.csv).stdout
        if not IoClass.compare_ioclass_lists(IoClass.csv_to_list(csv), default_list):
            TestRun.LOGGER.error("Default configuration does not match expected\n"
                                 f"Current:\n{csv}\n"
                                 f"Expected:{IoClass.list_to_csv(default_list)}")

    with TestRun.LOGGER.step("Create and load configuration file for 33 IO classes "
                             "with random names, allocation and priority values"):
        random_list = IoClass.generate_random_ioclass_list(33)
        IoClass.save_list_to_config_file(random_list, ioclass_config_path=ioclass_config_path)
        casadm.load_io_classes(cache.cache_id, ioclass_config_path)

    with TestRun.LOGGER.step("Display and export IO class configuration - displayed configuration "
                             "should be the same as created"):
        TestRun.executor.run(
            f"{casadm.list_io_classes_cmd(str(cache.cache_id), OutputFormat.csv.name)}"
            f" > {saved_config_path}")
        csv = fs_utils.read_file(saved_config_path)
        if not IoClass.compare_ioclass_lists(IoClass.csv_to_list(csv), random_list):
            TestRun.LOGGER.error("Exported configuration does not match expected\n"
                                 f"Current:\n{csv}\n"
                                 f"Expected:{IoClass.list_to_csv(random_list)}")

    with TestRun.LOGGER.step("Stop Intel CAS"):
        casadm.stop_cache(cache.cache_id)

    with TestRun.LOGGER.step("Start cache and add core"):
        cache = casadm.start_cache(cache.cache_device, force=True)
        casadm.add_core(cache, core.core_device)

    with TestRun.LOGGER.step("Check IO class configuration (should contain only default class)"):
        csv = casadm.list_io_classes(cache.cache_id, OutputFormat.csv).stdout
        if not IoClass.compare_ioclass_lists(IoClass.csv_to_list(csv), default_list):
            TestRun.LOGGER.error("Default configuration does not match expected\n"
                                 f"Current:\n{csv}\n"
                                 f"Expected:{IoClass.list_to_csv(default_list)}")

    with TestRun.LOGGER.step("Load exported configuration file for 33 IO classes"):
        casadm.load_io_classes(cache.cache_id, saved_config_path)

    with TestRun.LOGGER.step("Display IO class configuration - should be the same as created"):
        csv = casadm.list_io_classes(cache.cache_id, OutputFormat.csv).stdout
        if not IoClass.compare_ioclass_lists(IoClass.csv_to_list(csv), random_list):
            TestRun.LOGGER.error("Exported configuration does not match expected\n"
                                 f"Current:\n{csv}\n"
                                 f"Expected:{IoClass.list_to_csv(random_list)}")

    with TestRun.LOGGER.step(f"Test cleanup"):
        fs_utils.remove(saved_config_path)


def prepare(cache_mode: CacheMode = None):
    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks['cache']
    core_device = TestRun.disks['core']

    cache_device.create_partitions([Size(150, Unit.MebiByte)])
    core_device.create_partitions([Size(300, Unit.MebiByte)])

    cache_device = cache_device.partitions[0]
    core_device = core_device.partitions[0]

    TestRun.LOGGER.info(f"Starting cache")
    cache = casadm.start_cache(cache_device, cache_mode=cache_mode, force=True)
    TestRun.LOGGER.info(f"Adding core device")
    core = casadm.add_core(cache, core_dev=core_device)

    return cache, core
