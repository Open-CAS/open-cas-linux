#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import pytest
from datetime import timedelta

import test_tools.runlevel
from api.cas import ioclass_config, casadm_parser
from api.cas.cache_config import CacheMode
from api.cas.casadm_params import StatsFilter
from api.cas.init_config import InitConfig
from api.cas.ioclass_config import IoClass
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_tools.os_tools import sync, drop_caches
from test_tools.runlevel import Runlevel
from type_def.size import Size, Unit
from tests.io_class.io_class_common import (
    prepare,
    mountpoint,
    ioclass_config_path,
    compare_io_classes_list,
    run_io_dir_read,
    template_config_path,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("runlevel", [Runlevel.runlevel3, Runlevel.runlevel5])
def test_io_class_service_load(runlevel):
    """
    title: Open CAS service support for IO class - load.
    description: |
        Check Open CAS ability to load IO class configuration automatically on system start up.
    pass_criteria:
        - No system crash
        - IO class configuration is the same before and after reboot
    """
    with TestRun.step("Prepare devices."):
        cache, core = prepare(core_size=Size(300, Unit.MebiByte), cache_mode=CacheMode.WT)

    with TestRun.step("Read the whole CAS device."):
        run_io_dir_read(core.path)

    with TestRun.step("Create ext4 filesystem on CAS device and mount it."):
        core.create_filesystem(Filesystem.ext4)
        core.mount(mountpoint)

    with TestRun.step(
        "Load IO class configuration file with rules that metadata will not be "
        "cached and all other IO will be cached as unclassified."
    ):
        config_io_classes = prepare_and_load_io_class_config(cache, metadata_not_cached=True)

    with TestRun.step("Run IO."):
        run_io()

    with TestRun.step("Save IO class usage and configuration statistic."):
        saved_usage_stats = cache.get_io_class_statistics(
            io_class_id=0, stat_filter=[StatsFilter.usage]
        ).usage_stats
        saved_conf_stats = cache.get_io_class_statistics(
            io_class_id=0, stat_filter=[StatsFilter.conf]
        ).config_stats

    with TestRun.step("Create init config from running CAS configuration."):
        InitConfig.create_init_config_from_running_configuration(
            cache_extra_flags=f"ioclass_file={ioclass_config_path}"
        )
        sync()

    with TestRun.step(f"Reboot system to runlevel {runlevel}."):
        test_tools.runlevel.change_runlevel(runlevel)
        TestRun.executor.reboot()

    with TestRun.step(
        "Check if CAS device loads properly - "
        "IO class configuration and statistics shall not change"
    ):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail("Cache did not start at boot time.")
        cache = caches[0]
        cores = casadm_parser.get_cores(cache.cache_id)
        if len(cores) != 1:
            TestRun.fail(f"Actual number of cores: {len(cores)}\nExpected number of cores: 1")
        core = cores[0]
        output_io_classes = cache.list_io_classes()
        compare_io_classes_list(config_io_classes, output_io_classes)

        # Reads from core can invalidate some data so it is possible that occupancy after reboot
        # is lower than before
        reads_from_core = cache.get_statistics(stat_filter=[StatsFilter.blk]).block_stats.core.reads
        read_usage_stats = cache.get_io_class_statistics(
            io_class_id=0, stat_filter=[StatsFilter.usage]
        ).usage_stats
        read_conf_stats = cache.get_io_class_statistics(
            io_class_id=0, stat_filter=[StatsFilter.conf]
        ).config_stats

        if read_conf_stats != saved_conf_stats:
            TestRun.LOGGER.error(
                f"Statistics do not match. Before: {str(saved_conf_stats)} "
                f"After: {str(read_conf_stats)}"
            )
        if (
            read_usage_stats != saved_usage_stats
            and saved_usage_stats.occupancy - read_usage_stats.occupancy > reads_from_core
        ):
            TestRun.LOGGER.error(
                f"Statistics do not match. Before: {str(saved_usage_stats)} "
                f"After: {str(read_usage_stats)}"
            )

    with TestRun.step("Mount CAS device and run IO again."):
        core.mount(mountpoint)
        run_io()

    with TestRun.step("Check that data are mostly read from cache."):
        cache_stats = cache.get_statistics()
        read_hits = cache_stats.request_stats.read.hits
        read_total = cache_stats.request_stats.read.total
        read_hits_percentage = read_hits / read_total * 100
        if read_hits_percentage <= 95:
            TestRun.LOGGER.error(
                f"Read hits percentage too low: {read_hits_percentage}%\n"
                f"Read hits: {read_hits}, read total: {read_total}"
            )


def run_io():
    fio = (
        Fio()
        .create_command()
        .block_size(Size(1, Unit.Blocks4096))
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.read)
        .directory(os.path.join(mountpoint))
        .sync()
        .do_verify()
        .num_jobs(32)
        .run_time(timedelta(minutes=1))
        .time_based()
        .nr_files(30)
        .file_size(Size(250, Unit.KiB))
    )
    fio.run()

    sync()
    drop_caches()


def prepare_and_load_io_class_config(cache, metadata_not_cached=False):
    ioclass_config.remove_ioclass_config()

    if metadata_not_cached:
        ioclass_config.create_ioclass_config(
            add_default_rule=True, ioclass_config_path=ioclass_config_path
        )
        ioclass_config.add_ioclass(1, "metadata&done", 1, "0.00", ioclass_config_path)
    else:
        fs_utils.copy(template_config_path, ioclass_config_path)

    config_io_classes = IoClass.csv_to_list(fs_utils.read_file(ioclass_config_path))
    cache.load_io_class(ioclass_config_path)
    output_io_classes = cache.list_io_classes()
    if not IoClass.compare_ioclass_lists(config_io_classes, output_io_classes):
        TestRun.fail("Initial IO class configuration not loaded correctly, aborting test.")
    TestRun.LOGGER.info("Initial IO class configuration loaded correctly.")
    return config_io_classes
