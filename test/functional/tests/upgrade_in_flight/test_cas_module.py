#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
import os
import pytest
from git import Repo

from api.cas import installer, git, upgrade_in_flight, version
from api.cas.cache_config import CacheMode
from api.cas.cas_module import CasModule
from api.cas.casadm import start_cache, stop_all_caches
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.device import Device
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fs_utils import remove
from test_utils.os_utils import unload_kernel_module
from test_utils.output import CmdException
from test_utils.size import Size, Unit

cache_size = Size(1, Unit.GiB)
cache_modes_amount = len(set(list(CacheMode.__members__.values())))
cores_per_cache = 64
core_size = Size(128, Unit.MiB)
number_of_cores_to_remove = cores_per_cache // 4

test_path = os.path.realpath(__file__)
repo = Repo(test_path, search_parent_directories=True)
cas_version_to_upgrade = version.get_upgradable_cas_versions(repo.commit())[0]


@pytest.mark.od_dependent
@pytest.mark.uninstall_cas()
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_module_usage_counter_without_cores():
    """
    title: Validate OpenCAS module used by counter, no cores.
    description: |
      Validate OpenCAS kernel modules usage counter for cas_cache.ko and cas_disk.ko
      after starting many cache instances (one for each cache mode) without adding cores.
    pass_criteria:
      - Cannot remove OpenCAS kernel modules when usage counter is not 0.
      - OpenCAS increase and decrease cas_cache usage counter.
      - OpenCAS usage counter is equal to amount of caches.
    """
    with TestRun.step("Get current OpenCAS version and install older one."):
        installer.set_up_opencas()
        original_commit = git.get_current_commit_hash(from_dut=True)

        installer.uninstall_opencas()
        installer.set_up_opencas(cas_version_to_upgrade)

    with TestRun.step("Prepare cache devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([cache_size] * cache_modes_amount)

    with TestRun.step("Start caches."):
        caches = []
        cache_modes = get_all_cache_modes()
        for i, mode in enumerate(cache_modes):
            caches.append(start_cache(cache_dev.partitions[i], mode))

    with TestRun.step("Check module usage counters for cas_cache and cas_disk."):
        module_usage_before_upgrade = check_counters()
        cas_disk_usage_before_upgrade = module_usage_before_upgrade.get(CasModule.disk.value)
        cas_cache_usage_before_upgrade = module_usage_before_upgrade.get(CasModule.cache.value)

        if cas_disk_usage_before_upgrade != 1:
            TestRun.LOGGER.error(
                f"Module usage counter should show only 1 use of {CasModule.disk.value}."
            )

        if cas_cache_usage_before_upgrade != cache_modes_amount:
            TestRun.LOGGER.error(
                f"Module usage counter should show {cache_modes_amount} "
                f"uses of {CasModule.cache.value}."
            )

    with TestRun.step("Upgrade in flight OpenCAS and check reference counters."):
        installer._clean_opencas_repo()
        git.checkout_cas_version(original_commit)
        try:
            upgrade_in_flight.upgrade_start()
        except CmdException:
            restore_pretest_state(original_commit)
            TestRun.fail("Upgrade failed!")

        module_usage_after_upgrade = check_counters()
        cas_disk_usage_after_upgrade = module_usage_after_upgrade.get(CasModule.disk.value)
        cas_cache_usage_after_upgrade = module_usage_after_upgrade.get(CasModule.cache.value)

        if cas_disk_usage_after_upgrade != cas_disk_usage_before_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} after upgrade "
                f"should equal to this before upgrade."
            )

        if cas_cache_usage_after_upgrade != cas_cache_usage_before_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} after upgrade "
                f"should equal to this before upgrade."
            )

    with TestRun.step("Try to remove cas_cache and cas_disk modules."):
        try:
            unload_kernel_module(CasModule.cache.value)
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot remove OpenCAS kernel modules as expected.\n{exc}")

    with TestRun.step("Stop all caches and check module usage counters."):
        stop_all_caches()
        module_usage_after_stop = check_counters()
        cas_disk_usage_after_stop = module_usage_after_stop.get(CasModule.disk.value)
        cas_cache_usage_after_stop = module_usage_after_stop.get(CasModule.cache.value)

        if cas_disk_usage_after_stop != cas_disk_usage_after_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} after stop "
                f"should equal to this before upgrade."
            )

        if cas_cache_usage_after_stop == cas_cache_usage_after_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} after stop "
                f"should differ from this after upgrade."
            )

    with TestRun.step("Try to remove cas_disk module."):
        try:
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot remove {CasModule.disk.value} module as expected.\n{exc}")

    with TestRun.step("Try to remove cas_cache module and start OpenCAS."):
        try:
            unload_kernel_module(CasModule.cache.value)
            start_cache(cache_dev.partitions[0], load=True)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot start OpenCAS as expected.\n{exc}")

    with TestRun.step("Try to remove cas_disk module."):
        try:
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.error(f"Cannot remove {CasModule.disk.value} module.\n{exc}")

    with TestRun.step("Reinstall original OpenCAS version."):
        restore_pretest_state(original_commit)


@pytest.mark.od_dependent
@pytest.mark.uninstall_cas()
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_module_usage_counter_with_cores():
    """
    title: Validate OpenCAS module used by counter.
    description: |
      Validate OpenCAS kernel modules usage counter for cas_cache.ko and cas_disk.ko
      after starting many cache instances (one for each cache mode) with many cores.
    pass_criteria:
      - Cannot remove OpenCAS kernel modules when usage counter is not 0.
      - OpenCAS increase and decrease cas_cache usage counter.
      - OpenCAS usage counter is equal to sum of cores and caches.
    """
    with TestRun.step("Get current OpenCAS version and install older one."):
        installer.set_up_opencas()
        original_commit = git.get_current_commit_hash(from_dut=True)

        installer.uninstall_opencas()
        installer.set_up_opencas(cas_version_to_upgrade)

    with TestRun.step("Prepare cache devices."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(48, Unit.GiB)] + [cache_size] * cache_modes_amount)

    with TestRun.step("Create filesystem on the 1st partition of cache device and mount it."):
        cache_dev.partitions[0].create_filesystem(Filesystem.xfs)
        cache_dev.partitions[0].mount("/mnt/images")

    with TestRun.step(f"Create {cache_modes_amount * cores_per_cache} image files."):
        for i in range(cache_modes_amount * cores_per_cache):
            (Dd()
             .output(f"/mnt/images/data{i:0>3}")
             .input("/dev/zero")
             .block_size(Size(8, Unit.MiB))
             .count(16)
             .oflag("direct")
             ).run()

    with TestRun.step("Create loop device on created images."):
        loop_devices = []
        for i in range(cache_modes_amount * cores_per_cache):
            TestRun.executor.run_expect_success(
                f"losetup /dev/loop{i} /mnt/images/data{i:0>3}"
            )
            loop_devices.append(Device(f"/dev/loop{i}"))

    with TestRun.step("Start caches, one for each cache mode."):
        caches = []
        cache_modes = get_all_cache_modes()
        for i, mode in enumerate(cache_modes):
            caches.append(start_cache(cache_dev.partitions[i + 1], mode, force=True))

    with TestRun.step(f"Add {cores_per_cache} cores to each cache."):
        cores_on_cache = {}
        cores_offset = 0
        for cache in caches:
            cores = []
            cores_on_cache[cache.cache_id] = cores
            for i in range(cores_per_cache):
                cores.append(cache.add_core(loop_devices[cores_offset + i]))
            cores_offset += cores_per_cache

    with TestRun.step("Check module usage counters for cas_cache and cas_disk."):
        module_usage_before_upgrade = check_counters()
        cas_disk_usage_before_upgrade = module_usage_before_upgrade.get(CasModule.disk.value)
        cas_cache_usage_before_upgrade = module_usage_before_upgrade.get(CasModule.cache.value)

        if cas_disk_usage_before_upgrade != 1:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} mismatch!\n"
                f"Expected: 1\n"
                f"Actual: {cas_cache_usage_before_upgrade}"
            )

        expected_usage_before_upgrade = cache_modes_amount + (cache_modes_amount * cores_per_cache)
        if cas_cache_usage_before_upgrade != expected_usage_before_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} mismatch!\n"
                f"Expected: {expected_usage_before_upgrade}\n"
                f"Actual: {cas_cache_usage_before_upgrade}"
            )

    with TestRun.step("Upgrade in flight OpenCAS and check reference counters."):
        installer._clean_opencas_repo()
        git.checkout_cas_version(original_commit)
        try:
            upgrade_in_flight.upgrade_start()
        except CmdException:
            restore_pretest_state(original_commit)
            TestRun.fail("Upgrade failed!")

        module_usage_after_upgrade = check_counters()
        cas_disk_usage_after_upgrade = module_usage_after_upgrade.get(CasModule.disk.value)
        cas_cache_usage_after_upgrade = module_usage_after_upgrade.get(CasModule.cache.value)

        if cas_disk_usage_after_upgrade != cas_disk_usage_before_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} mismatch!\n"
                f"Expected: {cas_disk_usage_before_upgrade}\n"
                f"Actual: {cas_disk_usage_after_upgrade}"
            )

        if cas_cache_usage_after_upgrade != cas_cache_usage_before_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} mismatch!\n"
                f"Expected: {cas_cache_usage_before_upgrade}\n"
                f"Actual: {cas_cache_usage_after_upgrade}"
            )

    with TestRun.step("Try to remove cas_cache and cas_disk modules."):
        try:
            unload_kernel_module(CasModule.cache.value)
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot remove OpenCAS kernel modules as expected.\n{exc}")

    with TestRun.step(
            f"Remove {number_of_cores_to_remove} cores from each cache "
            f"and check module usage counters."
    ):
        for cache in caches:
            for core in cores_on_cache.get(cache.cache_id)[:number_of_cores_to_remove]:
                cache.remove_core(core.core_id)

        module_usage_after_remove = check_counters()
        cas_disk_usage_after_remove = module_usage_after_remove.get(CasModule.disk.value)
        cas_cache_usage_after_remove = module_usage_after_remove.get(CasModule.cache.value)

        if cas_disk_usage_after_remove != cas_disk_usage_after_upgrade:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} mismatch!\n"
                f"Expected: {cas_disk_usage_after_upgrade}\n"
                f"Actual: {cas_disk_usage_after_remove}"
            )

        expected_usage_after_remove = (
            expected_usage_before_upgrade - (cache_modes_amount * number_of_cores_to_remove)
        )
        if cas_cache_usage_after_remove != expected_usage_after_remove:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} mismatch!\n"
                f"Expected: {expected_usage_after_remove}\n"
                f"Actual: {cas_cache_usage_after_remove}"
            )

    with TestRun.step("Stop all caches and check module usage counters."):
        stop_all_caches()
        module_usage_after_stop = check_counters()
        cas_disk_usage_after_stop = module_usage_after_stop.get(CasModule.disk.value)
        cas_cache_usage_after_stop = module_usage_after_stop.get(CasModule.cache.value)

        if cas_disk_usage_after_stop != cas_disk_usage_after_remove:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.disk.value} mismatch!\n"
                f"Expected: {cas_disk_usage_after_remove}\n"
                f"Actual: {cas_disk_usage_after_stop}"
            )

        if cas_cache_usage_after_stop == cas_cache_usage_after_remove:
            TestRun.LOGGER.error(
                f"Module usage counter of {CasModule.cache.value} mismatch!\n"
                f"Expected: other than {cas_cache_usage_after_remove}\n"
                f"Actual: {cas_cache_usage_after_stop}"
            )

    with TestRun.step("Try to remove cas_disk module."):
        try:
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot remove {CasModule.disk.value} module as expected.\n{exc}")

    with TestRun.step("Try to remove cas_cache module and start OpenCAS."):
        try:
            unload_kernel_module(CasModule.cache.value)
            start_cache(cache_dev.partitions[0], force=True)
        except CmdException as exc:
            TestRun.LOGGER.info(f"Cannot start OpenCAS as expected.\n{exc}")

    with TestRun.step("Try to remove cas_disk module."):
        try:
            unload_kernel_module(CasModule.disk.value)
        except CmdException as exc:
            TestRun.LOGGER.error(f"Cannot remove {CasModule.disk.value} module.\n{exc}")

    with TestRun.step("Reinstall original OpenCAS version."):
        restore_pretest_state(original_commit)


def check_counters():
    module_counter = {}

    output = TestRun.executor.run_expect_success(
        f"lsmod | grep -e ^{CasModule.cache.value} -e ^{CasModule.disk.value}"
    )
    output = output.stdout.splitlines()
    for line in output:
        module_counter[line.split()[0]] = int(line.split()[2])

    return module_counter


def get_all_cache_modes():
    modes_list = []
    for mode in CacheMode:
        modes_list.append(mode)
    return modes_list


def restore_pretest_state(commit):
    TestRun.executor.run_expect_success("losetup -D")
    remove("/mnt/images", True, True, True)
    installer.uninstall_opencas()
    installer.set_up_opencas(commit)
