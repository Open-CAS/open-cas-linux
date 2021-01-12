#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
import os
from itertools import cycle
from time import sleep

from api.cas import casadm, casctl, casadm_parser
from api.cas.casadm import list_caches
from api.cas.casadm_parser import get_caches, get_cores, get_cas_devices_dict
from api.cas.cache_config import CacheMode
from api.cas.cli_messages import check_stdout_msg, no_caches_running
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_utils import parse_ls_output, ls, readlink
from test_utils.filesystem.file import File
from test_tools.disk_utils import Filesystem
from test_utils import fstab
from test_tools.dd import Dd
from test_utils.filesystem.symlink import Symlink
from test_utils.os_utils import drop_caches, sync
from test_utils.size import Unit, Size


mountpoint = "/mnt"
filepath = f"{mountpoint}/file"
cores_number = 4
by_id_dir = '/dev/disk/by-id/'


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_cas_startup(cache_mode, filesystem):
    """
    title: Test for starting CAS on system startup.
    pass_criteria:
      - System does not crash.
      - CAS modules are loaded before partitions are mounted.
      - Cache is loaded before partitions are mounted.
      - Exported object is mounted after startup is complete.
    """
    with TestRun.step("Prepare partitions for cache (200MiB) and for core (400MiB)"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        core = cache.add_core(core_part)

    with TestRun.step("Create and mount filesystem"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(filepath)
            .count(16)
            .block_size(Size(1, Unit.MebiByte))
            .run()
        )
        test_file = File(filepath)
        md5_before = test_file.md5sum()

    with TestRun.step("Add mountpoint fstab and create intelcas.conf"):
        fstab.add_mountpoint(device=core,
                             mount_point=mountpoint,
                             fs_type=filesystem)
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot"):
        TestRun.executor.reboot()

    with TestRun.step("Check if cache is started"):
        caches = list(get_caches())
        if len(caches) != 1:
            TestRun.fail(f"Expected one cache, got {len(caches)}!")
        if caches[0].cache_id != cache.cache_id:
            TestRun.fail("Invalid cache id!")

    with TestRun.step("Check if core is added"):
        cores = list(get_cores(cache.cache_id))
        if len(cores) != 1:
            TestRun.fail(f"Expected one core, got {len(cores)}!")
        if cores[0].core_id != core.core_id:
            TestRun.fail("Invalid core id!")

    with TestRun.step("Check if filesystem is mounted"):
        if not core.is_mounted():
            TestRun.fail("Core is not mounted!")

    with TestRun.step("Check if md5 checksum matches"):
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")

    with TestRun.step("Test cleanup"):
        fstab.remove_mountpoint(device=core)
        core.unmount()
        InitConfig.create_default_init_config()
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode_pair", [(CacheMode.WT, CacheMode.WB),
                                              (CacheMode.WB, CacheMode.WA),
                                              (CacheMode.WA, CacheMode.PT),
                                              (CacheMode.PT, CacheMode.WO),
                                              (CacheMode.WO, CacheMode.WT)])
def test_cas_init_with_changed_mode(cache_mode_pair):
    """
    title: Check starting cache in other cache mode by initializing OpenCAS service from config.
    description: |
      Start cache, create config based on running configuration but with another cache mode,
      reinitialize OpenCAS service with '--force' option and check if cache defined
      in config file starts properly.
      Check all cache modes.
    pass_criteria:
      - Cache starts with attached core
      - Cache starts in mode saved in configuration file.
    """
    with TestRun.step("Prepare partitions for cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step(f"Start cache in the {cache_mode_pair[0]} mode and add core."):
        cache = casadm.start_cache(cache_part, cache_mode_pair[0], force=True)
        core = cache.add_core(core_part)

    with TestRun.step(
            f"Create the configuration file with a different cache mode ({cache_mode_pair[1]})"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(cache.cache_id, cache.cache_device, cache_mode_pair[1])
        init_conf.add_core(cache.cache_id, core.core_id, core.core_device)
        init_conf.save_config_file()

    with TestRun.step("Reinitialize OpenCAS service with '--force' option."):
        casadm.stop_all_caches()
        casctl.init(True)

    with TestRun.step("Check if cache started in correct mode with core attached."):
        validate_cache(cache_mode_pair[1])


def validate_cache(cache_mode):
    caches = casadm_parser.get_caches()
    caches_count = len(caches)
    if caches_count != 1:
        TestRun.LOGGER.error(
            f"Cache did not start successfully - wrong number of caches: {caches_count}."
        )

    cores = casadm_parser.get_cores(caches[0].cache_id)
    cores_count = len(cores)
    if cores_count != 1:
        TestRun.LOGGER.error(f"Cache started with wrong number of cores: {cores_count}.")

    current_mode = caches[0].get_cache_mode()
    if current_mode != cache_mode:
        TestRun.LOGGER.error(
            f"Cache started in wrong mode!\n"
            f"Should start in {cache_mode}, but started in {current_mode} mode."
        )


@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("reboot_type", ["soft", "hard"])
def test_cas_startup_core_path_by_id(cache_mode, reboot_type):
    """
    title: Test for CAS startup when cores are set in config with wrong by-id path.
    description: |
      Start cache, add to config different fo links to devices that make up the cache
      and check if cache start fails after reboot. Clear cache metadata before reboot.
    pass_criteria:
      - System does not crash
      - Cache is running after startup
      - Cores are detached after startup
    """
    with TestRun.step("Clearing dmesg"):
        TestRun.executor.run_expect_success("dmesg -C")

    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step(f"Find symlinks to {core_dev.path} in {by_id_dir}."):
        links = [
            Symlink(os.path.join(by_id_dir, item.full_path))       # parse_ls_output returns
            for item in parse_ls_output(ls(by_id_dir), by_id_dir)  # symlinks without path
            if isinstance(item, Symlink)
        ]
        core_dev_links = [link for link in links if readlink(core_dev.path) in link.get_target()]

    with TestRun.step(f"Select different links to {core_dev.path} partitions."):
        selected_links = select_links(core_dev_links)

    with TestRun.step("Start cache and add cores."):
        cores = []
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        for i in range(cores_number):
            core_dev.partitions[i].path = selected_links[i].full_path
            cores.append(cache.add_core(core_dev.partitions[i]))

    with TestRun.step("Create opencas.conf."):
        create_init_config(cache, cores, [link.full_path for link in selected_links])
        drop_caches()
        sync()

    with TestRun.step("Stop cache and clear metadata before reboot."):
        cache.stop()
        casadm.zero_metadata(cache_part)

    with TestRun.step("Reset platform."):
        if reboot_type == "soft":
            TestRun.executor.reboot()
        else:           # wait few seconds to simulate power failure during normal system run
            sleep(5)    # not when configuring Open CAS
            power_control = TestRun.plugin_manager.get_plugin('power_control')
            power_control.power_cycle()

    with TestRun.step("Check if all cores are detached."):
        listed_cores = get_cas_devices_dict().get("core_pool")
        listed_cores_number = len(listed_cores)
        if listed_cores_number != cores_number:
            TestRun.fail(f"Expected {cores_number} cores, got {listed_cores_number}!")

        for core in listed_cores:
            if core.get("status") != "Detached":
                TestRun.fail(f"Core {core.get('device')} isn't detached as expected.")


def select_links(links):
    selected_links = []
    prev_starts_with = " "
    prev_ends_with = " "
    links_cycle = cycle(links)

    while len(selected_links) < cores_number:
        link = next(links_cycle)
        if '-part' not in link.name:
            continue
        if (
                link.get_target() not in [sel_link.get_target() for sel_link in selected_links]
                and not link.name.startswith(prev_starts_with)
                and not link.name.endswith(prev_ends_with)
        ):
            selected_links.append(link)
            prev_ends_with = link.name.split('-')[-1]
            prev_starts_with = link.name[:(link.name.index(prev_ends_with) - 1)]

    return selected_links


def create_init_config(cache, cores, paths):
    init_conf = InitConfig()

    def _add_core(core, path):
        params = [str(cache.cache_id), str(core.core_id), path, "lazy_startup=true"]
        init_conf.core_config_lines.append('\t'.join(params))

    init_conf.add_cache(
        cache.cache_id, cache.cache_device, cache.get_cache_mode(), "lazy_startup=true"
    )
    for i in range(cores_number):
        _add_core(cores[i], paths[i])
    init_conf.save_config_file()
    return init_conf
