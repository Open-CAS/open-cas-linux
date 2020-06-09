#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from collections import namedtuple
from contextlib import suppress
from datetime import timedelta
import os
import random

from api.cas import casadm, version
from api.cas.cache_config import CacheMode, CacheIds, CoreIds
from api.cas.cas_module import CasModule
from api.cas.casadm_params import OutputFormat
from api.cas.casadm_parser import (
    get_cas_cache_version,
    get_cas_disk_version,
    get_casadm_version,
    get_statistics,
)
from api.cas.init_config import InitConfig
from api.cas.installer import uninstall_opencas, set_up_opencas
from api.cas.ioclass_config import IoClass, MAX_IO_CLASS_ID
from api.cas.statistics import CacheStats, CoreStats
from core.test_run import TestRun
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from test_tools.fs_utils import create_directory, remove
from test_utils.filesystem.file import File
from test_utils.os_utils import get_module_path, kill_all_io
from test_utils.output import CmdException
from test_utils.size import Unit, Size


ioclasses_dir = "/tmp/test_upgrade_in_flight_ioclasses"


TestedConfig = namedtuple(
    "TestedConfig", "cache_part core_part cache_mode cache_id core_id ioclass_config"
)


def upgrade_compare_ioclass_config(original, cache_id):
    try:
        actual = casadm.list_io_classes(
            cache_id=cache_id, output_format=OutputFormat.csv
        ).stdout
    except CmdException:
        TestRun.LOGGER.error(f"Failed to retrive cache {cache_id} ioclass list")
        return

    actual = actual.splitlines()
    actual = [IoClass.from_string(ioclass) for ioclass in actual[1:]]

    if len(actual) != len(original):
        TestRun.LOGGER.error(
            f"Cache {cache_id}: expected {len(original)}, "
            f"got {len(actual)} ioclasses"
        )

    for gen, load in zip(original, actual):
        if gen != load:
            TestRun.LOGGER.error(
                f"Cache {cache_id}: expected {len(original)}, "
                f"got {len(actual)} ioclasses"
            )


def upgrade_check_files_updated(original):
    for old in original:
        actual_modification_time = File(old.full_path).refresh_item().modification_time
        if old.modification_time >= actual_modification_time:
            TestRun.LOGGER.error(f"{old.full_path} not updated during upgrade")


def upgrade_check_files_not_updated(original):
    for f in original:
        actual_modification_time = File(f.full_path).refresh_item().modification_time
        if f.modification_time != actual_modification_time:
            TestRun.LOGGER.error(
                f"{f.full_path} should not be updated during upgrade"
            )


def upgrade_get_cas_files(cas_version: version.CasVersion):
    paths = version.get_installed_files_list(cas_version)
    paths.remove(get_module_path(CasModule.disk.value))

    files_to_update = [File(f).refresh_item() for f in paths]

    return files_to_update


def upgrade_compare_cache_conf_section(original):
    try:
        actual = CacheStats(
            get_statistics(
                cache_id=int(original.cache_id), filter=[casadm.StatsFilter.conf]
            )
        ).config_stats
    except CmdException:
        TestRun.LOGGER.error(
            f"Cache {int(original.cache_id)} in {original.write_policy} on {original.cache_dev} "
            f"is not running after upgrade"
        )
        return

    error_message_template = f"Cache {int(original.cache_id)} " + "expected {}, got {}"
    stats_to_compare = [
        "cache_dev",
        "eviction_policy",
        "cleaning_policy",
        "promotion_policy",
        "cache_line_size",
        "status",
        "write_policy",
    ]

    __compare_stats(original, actual, stats_to_compare, error_message_template)


def upgrade_compare_core_conf_section(original, cache_id):
    cache_id = int(cache_id)
    try:
        actual = CoreStats(
            get_statistics(
                cache_id=cache_id,
                core_id=int(original.core_id),
                filter=[casadm.StatsFilter.conf],
            )
        ).config_stats
    except CmdException:
        TestRun.LOGGER.error(
            f"Cache {cache_id} has missing core {original.core_id} on {original.core_dev}"
        )
        return

    error_message_template = (
        f"Cache {cache_id}, core {int(original.core_id)} " + "expected {}, got {}"
    )
    stats_to_compare = [
        "exp_obj",
        "core_dev",
        "status",
        "seq_cutoff_threshold",
        "seq_cutoff_policy",
    ]

    __compare_stats(original, actual, stats_to_compare, error_message_template)


def __compare_stats(expected, actual, attributes_list, error_message_template):
    for stat in attributes_list:
        original_val = getattr(expected, stat)
        actual_val = getattr(actual, stat)

        if original_val != actual_val:
            TestRun.LOGGER.error(
                error_message_template.format(original_val, actual_val)
            )


def upgrade_verify_version_cmd(
    original_cas_disk_version, original_cas_cache_version, original_casadm_version
):
    final_casadm_version = get_casadm_version()
    final_cas_cache_version = get_cas_cache_version()
    final_cas_disk_version = get_cas_disk_version()

    if original_casadm_version != final_casadm_version:
        TestRun.LOGGER.error(
            f"casadm {final_casadm_version} version is installed "
            f"instead of expected {original_casadm_version}"
        )

    if original_cas_cache_version != final_cas_cache_version:
        TestRun.LOGGER.error(
            f"cas_cache.ko {final_cas_cache_version} version is installed "
            f"instead of expected {original_cas_cache_version}"
        )

    if original_cas_disk_version != final_cas_disk_version:
        TestRun.LOGGER.error(
            f"cas_disk.ko {final_cas_disk_version} version is installed "
            f"instead of expected {original_cas_disk_version}"
        )


def upgrade_prepare_caches(cache_line_size):
    TestRun.LOGGER.info(
        "Prepare partitions for caches (400MiB) and for cores (800MiB) - one per each cache mode"
    )
    number_of_caches = len(CacheMode)
    cache_dev = TestRun.disks["cache"]
    cache_dev.create_partitions([Size(400, Unit.MebiByte)] * number_of_caches)
    core_dev = TestRun.disks["core"]
    core_dev.create_partitions([Size(800, Unit.MebiByte)] * number_of_caches)

    TestRun.LOGGER.info("Create directory to store ioclass config files")
    with suppress(Exception):
        create_directory(ioclasses_dir)

    TestRun.LOGGER.info("Prepare configs")
    caches = []

    ioclass_configs = [
        IoClass.generate_random_ioclass_list(
            count=random.randint(0, MAX_IO_CLASS_ID), blacklist=["file_name_prefix"]
        )
        for _ in range(number_of_caches)
    ]

    configs = [
        TestedConfig(*c)
        for c in zip(
            cache_dev.partitions,
            core_dev.partitions,
            CacheMode,
            CacheIds.get_random_id(ids_number=number_of_caches),
            CoreIds.get_random_id(ids_number=number_of_caches),
            ioclass_configs,
        )
    ]

    TestRun.LOGGER.info("Create directory to store ioclass config files")
    with suppress(Exception):
        create_directory(ioclasses_dir)

    TestRun.LOGGER.info("Start caches, add cores")
    for c in configs:
        cache = casadm.start_cache(
            c.cache_part,
            cache_mode=c.cache_mode,
            cache_line_size=cache_line_size,
            cache_id=c.cache_id,
            force=True,
        )
        caches.append(cache)
        core = cache.add_core(c.core_part, core_id=c.core_id)

        IoClass.save_list_to_config_file(
            c.ioclass_config,
            add_default_rule=False,
            ioclass_config_path=os.path.join(ioclasses_dir, f"cache{c.cache_id}"),
        )
        cache.load_io_class(os.path.join(ioclasses_dir, f"cache{c.cache_id}"))

    TestRun.LOGGER.info("Save current caches to opencas.conf")
    original_init_config = (
        InitConfig.create_init_config_from_running_configuration()
    )

    return caches, configs


def upgrade_teardown(original_cas_version=None):
    remove(ioclasses_dir, force=True, recursive=True)
    kill_all_io()
    casadm.stop_all_caches()

    if original_cas_version is None:
        return

    uninstall_opencas()
    set_up_opencas(original_cas_version)


def upgrade_get_fio_cmd(core):
    fio = (
        Fio()
        .create_command()
        .target(core)
        .read_write(ReadWrite.randrw)
        .write_percentage(70)
        .io_engine(IoEngine.libaio)
        .block_size(Size(1, Unit.Blocks4096))
        .run_time(timedelta(minutes=30))
        .time_based(timedelta(minutes=30))
        .io_depth(32)
        .num_jobs(72)
        .direct(1)
        .verify(VerifyMethod.md5)
    )
    return fio
