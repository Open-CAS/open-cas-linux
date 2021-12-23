#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
from random import shuffle

import pytest

from api.cas import casadm, cli, cli_messages
from api.cas.cache_config import CacheStatus, SeqCutOffPolicy, CacheModeTrait, CacheMode, \
    CleaningPolicy, FlushParametersAlru
from api.cas.core import CoreStatus
from api.cas.init_config import InitConfig
from api.cas.statistics import CacheStats
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.filesystem.file import File
from test_utils.os_utils import Udev, sync
from test_utils.output import CmdException
from test_utils.size import Size, Unit
from test_utils.time import Time


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_attach_core_to_incomplete_cache_volume():
    """
        title: Test for attaching device to inactive cache volume.
        description: |
          Try to attach core device to inactive cache volume and check if it is visible in OS
          properly.
        pass_criteria:
          - No kernel error
          - Core status changes properly
          - Cache loads with inactive core device
          - Cache status changes properly
          - Exported object is present only for active core
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 1)])
        cache_dev = devices["cache"].partitions[0]
        core_dev = devices["core"].partitions[0]
        plug_device = devices["core"]

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Load cache."):
        casadm.load_cache(cache_dev)

    with TestRun.step("Check if there is CAS device in /dev and core is in active status."):
        core.check_if_is_present_in_os()
        core_status = core.get_status()
        if core_status != CoreStatus.active:
            TestRun.fail(f"Core should be in active state. (Actual: {core_status})")

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug core device."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Check if there is no CAS device in /dev and core is in inactive status."):
        core.check_if_is_present_in_os(False)
        if core.get_status() != CoreStatus.inactive:
            TestRun.fail("Core should be in inactive state.")

    with TestRun.step("Plug core device."):
        plug_device.plug()
        time.sleep(1)

    with TestRun.step("Check if core status changed to active and CAS device is visible in OS."):
        core.wait_for_status_change(CoreStatus.active)
        core.check_if_is_present_in_os()
        if cache.get_status() != CacheStatus.running:
            TestRun.fail("Cache did not change status to 'running' after plugging core device.")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
def test_flush_inactive_devices():
    """
        title: Negative test for flushing inactive CAS devices.
        description: Validate that CAS prevents flushing dirty data from inactive CAS devices.
        pass_criteria:
          - No kernel error
          - Exported object appears after plugging core device
          - Flushing inactive CAS devices is possible neither by cleaning thread,
            nor by calling cleaning methods
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core1", 1), ("core2", 1)])
        cache_dev = devices["cache"].partitions[0]
        first_core_dev = devices["core1"].partitions[0]
        second_core_dev = devices["core2"].partitions[0]
        plug_device = devices["core1"]

    with TestRun.step("Start cache in WB mode and set alru cleaning policy."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cache.set_cleaning_policy(CleaningPolicy.alru)
        cache.set_params_alru(FlushParametersAlru(
            staleness_time=Time(seconds=10),
            wake_up_time=Time(seconds=1),
            activity_threshold=Time(milliseconds=500)))

    with TestRun.step("Add two cores."):
        first_core = cache.add_core(first_core_dev)
        second_core = cache.add_core(second_core_dev)

    with TestRun.step("Create init config file using running CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Run random writes to CAS device."):
        run_fio([first_core.path, second_core.path])

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Unplug one core disk."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Wait longer than required for alru cleaning thread to start and verify "
                      "that dirty data is flushed only from active device."):
        dirty_lines_before = {first_core: first_core.get_dirty_blocks(),
                              second_core: second_core.get_dirty_blocks()}
        time.sleep(30)
        check_amount_of_dirty_data(dirty_lines_before)

    with TestRun.step("Try to call 'flush cache' command."):
        dirty_lines_before = {first_core: first_core.get_dirty_blocks(),
                              second_core: second_core.get_dirty_blocks()}
        try:
            cache.flush_cache()
            TestRun.fail("Flush cache operation should be blocked due to inactive cache devices, "
                         "but it executed successfully.")
        except Exception as e:
            TestRun.LOGGER.info(f"Flush cache operation is blocked as expected.\n{str(e)}")
            check_amount_of_dirty_data(dirty_lines_before)

    with TestRun.step("Try to call 'flush core' command for inactive core."):
        dirty_lines_before = {first_core: first_core.get_dirty_blocks(),
                              second_core: second_core.get_dirty_blocks()}
        try:
            first_core.flush_core()
            TestRun.fail("Flush core operation should be blocked for inactive CAS devices, "
                         "but it executed successfully.")
        except Exception as e:
            TestRun.LOGGER.info(f"Flush core operation is blocked as expected.\n{str(e)}")
            check_amount_of_dirty_data(dirty_lines_before)

    with TestRun.step("Plug core disk and verify that this change is reflected on the cache list."):
        plug_device.plug()
        time.sleep(1)
        first_core.wait_for_status_change(CoreStatus.active)
        cache_status = cache.get_status()
        if cache_status != CacheStatus.running:
            TestRun.fail(f"Cache did not change status to 'running' after plugging core device. "
                         f"Actual state: {cache_status}.")

    with TestRun.step("Stop cache."):
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_list_cache_and_cache_volumes():
    """
        title: List cache with cache volumes and check their status.
        description: |
          Check if casadm command correctly lists caches and cache volumes with their statuses.
        pass_criteria:
          - No kernel error
          - Output of list command should be correct in each case (as described in test steps)
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 1)])
        cache_dev = devices["cache"].partitions[0]
        core_dev = devices["core"].partitions[0]
        plug_device = devices["core"]

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Check if list caches command shows proper output (cache should have status "
                      "Running and cache volume should be Active)."):
        core_status = core.get_status()
        if core_status != CoreStatus.active:
            TestRun.fail(f"Core should be in active state. Actual state: {core_status}.")
        cache_status = cache.get_status()
        if cache_status != CacheStatus.running:
            TestRun.fail(f"Cache should be in running state. Actual state: {cache_status}")

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug core device."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Check if list cache command shows proper output (cache should have status "
                      "Incomplete and cache volume should be Inactive)."):
        core_status = core.get_status()
        if core_status != CoreStatus.inactive:
            TestRun.fail(f"Core should be in inactive state. Actual state: {core_status}.")
        cache_status = cache.get_status()
        if cache_status != CacheStatus.incomplete:
            TestRun.fail(f"Cache should be in incomplete state. Actual state: {cache_status}.")

    with TestRun.step("Plug missing device and stop cache."):
        plug_device.plug()
        time.sleep(1)
        core.wait_for_status_change(CoreStatus.active)
        cache_status = cache.get_status()
        if cache_status != CacheStatus.running:
            TestRun.fail(f"Cache did not change status to 'running' after plugging core device. "
                         f"Actual state: {cache_status}")
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_cache_with_inactive_core():
    """
        title: Load cache with unavailable core devices.
        description: Check if it is possible to load cache with unavailable core devices.
        pass_criteria:
          - No kernel error
          - It is possible to perform cache load operation with unavailable devices.
          - Warning message about not available core device should appear.
          - Cache status should change to active after plugging missing core device.
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 1)])
        cache_dev = devices["cache"].partitions[0]
        core_dev = devices["core"].partitions[0]
        plug_device = devices["core"]

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step("Unplug core device."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        output = TestRun.executor.run(cli.load_cmd(cache_dev.path))
        cli_messages.check_stderr_msg(output, cli_messages.load_inactive_core_missing)

    with TestRun.step("Plug missing device and stop cache."):
        plug_device.plug()
        time.sleep(1)
        core.wait_for_status_change(CoreStatus.active)
        cache_status = cache.get_status()
        if cache_status != CacheStatus.running:
            TestRun.fail(f"Cache did not change status to 'running' after plugging core device. "
                         f"Actual state: {cache_status}.")
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_preserve_data_for_inactive_device():
    """
        title: Validate preserving data for inactive CAS devices.
        description: Validate that cached data for inactive CAS devices is preserved.
        pass_criteria:
          - No kernel error
          - File md5 checksums match in every iteration.
          - Cache read hits increase after reads (md5 checksum) from CAS device with attached core.
    """
    mount_dir = "/mnt/test"
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 1)])
        cache_dev = devices["cache"].partitions[0]
        core_dev = devices["core"].partitions[0]
        plug_device = devices["core"]

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Create filesystem on CAS device and mount it."):
        core.create_filesystem(Filesystem.ext3)
        core.mount(mount_dir)

    with TestRun.step("Create a test file with random writes on mount point and count it's md5."):
        file_path = f"{mount_dir}/test_file"
        test_file = File.create_file(file_path)
        dd = Dd().input("/dev/random") \
            .output(file_path) \
            .count(100) \
            .block_size(Size(1, Unit.Blocks512))
        dd.run()
        sync()
        md5_after_create = test_file.md5sum()
        cache_stats_before_stop = cache.get_statistics()
        core_stats_before_stop = core.get_statistics()

    with TestRun.step("Unmount CAS device."):
        core.unmount()

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Unplug core device."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)
        cache_stats_after_load = cache.get_statistics()
        core_stats_after_load = core.get_statistics()
        if (
            cache_stats_before_stop.usage_stats.clean != cache_stats_after_load.usage_stats.clean
            or cache_stats_before_stop.usage_stats.dirty != cache_stats_after_load.usage_stats.dirty
            or core_stats_before_stop.usage_stats.clean != core_stats_after_load.usage_stats.clean
            or core_stats_before_stop.usage_stats.dirty != core_stats_after_load.usage_stats.dirty
        ):
            TestRun.fail(f"Statistics after counting md5 are different than after cache load.\n"
                         f"Cache stats before: {cache_stats_before_stop}\n"
                         f"Cache stats after: {cache_stats_after_load}\n"
                         f"Core stats before: {core_stats_before_stop}\n"
                         f"Core stats after: {core_stats_after_load}")

    with TestRun.step("Plug core disk using sysfs and verify this change is reflected "
                      "on the cache list."):
        plug_device.plug()
        time.sleep(1)
        if cache.get_status() != CacheStatus.running or core.get_status() != CoreStatus.active:
            TestRun.fail(f"Expected cache status is running (actual - {cache.get_status()}).\n"
                         f"Expected core status is active (actual - {core.get_status()}).")

    with TestRun.step("Mount CAS device"):
        core.mount(mount_dir)

    with TestRun.step("Count md5 checksum for test file and compare it with previous value."):
        cache_read_hits_before_md5 = cache.get_statistics().request_stats.read.hits
        md5_after_cache_load = test_file.md5sum()
        if md5_after_create != md5_after_cache_load:
            TestRun.fail("Md5 checksum after cache load operation is different than before "
                         "stopping cache.")
        else:
            TestRun.LOGGER.info("Md5 checksum is identical before and after cache load operation "
                                "with inactive CAS device.")

    with TestRun.step("Verify that cache read hits increased after counting md5 checksum."):
        cache_read_hits_after_md5 = cache.get_statistics().request_stats.read.hits
        if cache_read_hits_after_md5 - cache_read_hits_before_md5 < 0:
            TestRun.fail(f"Cache read hits did not increase after counting md5 checksum. "
                         f"Before: {cache_read_hits_before_md5}. "
                         f"After: {cache_read_hits_after_md5}.")
        else:
            TestRun.LOGGER.info("Cache read hits increased as expected.")

    with TestRun.step("Unmount CAS device and stop cache."):
        core.unmount()
        cache.stop()


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeSet([DiskType.sata, DiskType.hdd, DiskType.hdd4k]))
@pytest.mark.require_disk("core2", DiskTypeSet([DiskType.sata, DiskType.hdd, DiskType.hdd4k]))
def test_print_statistics_inactive(cache_mode):
    """
        title: Print statistics for cache with inactive cache volumes.
        description: |
          Check if statistics are displayed properly when there is one or more
          inactive cache volumes added to cache.
        pass_criteria:
          - No kernel error
          - All statistics should contain appropriate information depending on situation of
            cache and core devices (as described in test steps)
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core1", 1), ("core2", 1)])
        cache_dev = devices["cache"].partitions[0]
        first_core_dev = devices["core1"].partitions[0]
        second_core_dev = devices["core2"].partitions[0]
        first_plug_device = devices["core1"]
        second_plug_device = devices["core2"]
        Udev.disable()  # disabling udev for a while prevents creating clean data on cores

    with TestRun.step("Start cache and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=cache_mode, force=True)
        first_core = cache.add_core(first_core_dev)
        second_core = cache.add_core(second_core_dev)
        cache_mode_traits = CacheMode.get_traits(cache.get_cache_mode())

    with TestRun.step("Disable cleaning and sequential cutoff policies."):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Run IO."):
        run_fio([first_core.path, second_core.path])

    with TestRun.step("Print statistics and check if there is no inactive usage section."):
        active_stats = cache.get_statistics()
        check_if_inactive_section_exists(active_stats, False)

    with TestRun.step("Stop cache."):
        if CacheModeTrait.LazyWrites in cache_mode_traits:
            cache.stop(no_data_flush=True)
        else:
            cache.stop()

    with TestRun.step("Remove both core devices from OS."):
        Udev.enable()  # enable udev back because it's necessary now
        first_plug_device.unplug()
        second_plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Check if inactive devices section appeared and contains appropriate "
                      "information."):
        inactive_stats_before = cache.get_statistics()
        check_if_inactive_section_exists(inactive_stats_before)
        check_number_of_inactive_devices(inactive_stats_before, 2)

    with TestRun.step("Attach one of detached core devices and add it to cache."):
        first_plug_device.plug()
        time.sleep(1)
        first_core_status = first_core.get_status()
        if first_core_status != CoreStatus.active:
            TestRun.fail(f"Core {first_core.path} should be in active state but it is not. "
                         f"Actual state: {first_core_status}.")

    with TestRun.step("Check cache statistics section of inactive devices."):
        inactive_stats_after = cache.get_statistics()
        check_if_inactive_section_exists(inactive_stats_after)
        check_number_of_inactive_devices(inactive_stats_after, 1)
        # criteria for checks below
        insert_write_traits = CacheModeTrait.InsertWrite in cache_mode_traits
        lazy_write_traits = CacheModeTrait.LazyWrites in cache_mode_traits
        lazy_writes_or_no_insert_write_traits = (not insert_write_traits
                                                 or lazy_write_traits)

        check_inactive_usage_stats(inactive_stats_before.inactive_usage_stats.inactive_occupancy,
                                   inactive_stats_after.inactive_usage_stats.inactive_occupancy,
                                   "inactive occupancy",
                                   not insert_write_traits)
        check_inactive_usage_stats(inactive_stats_before.inactive_usage_stats.inactive_clean,
                                   inactive_stats_after.inactive_usage_stats.inactive_clean,
                                   "inactive clean",
                                   lazy_writes_or_no_insert_write_traits)
        check_inactive_usage_stats(inactive_stats_before.inactive_usage_stats.inactive_dirty,
                                   inactive_stats_after.inactive_usage_stats.inactive_dirty,
                                   "inactive dirty",
                                   not lazy_write_traits)

    with TestRun.step("Check statistics per inactive core."):
        inactive_core_stats = second_core.get_statistics()
        if inactive_stats_after.inactive_usage_stats.inactive_occupancy == \
                inactive_core_stats.usage_stats.occupancy:
            TestRun.LOGGER.info("Inactive occupancy in cache statistics is equal to inactive core "
                                "occupancy.")
        else:
            TestRun.fail(f"Inactive core occupancy ({inactive_core_stats.usage_stats.occupancy}) "
                         f"should be the same as cache inactive occupancy "
                         f"({inactive_stats_after.inactive_usage_stats.inactive_occupancy}).")

    with TestRun.step("Remove inactive core from cache and check if cache is in running state."):
        cache.remove_inactive_core(second_core.core_id)
        cache_status = cache.get_status()
        if cache_status != CacheStatus.running:
            TestRun.fail(f"Cache did not change status to 'running' after plugging core device. "
                         f"Actual status: {cache_status}.")

    with TestRun.step("Check if there is no inactive devices statistics section and if cache has "
                      "Running status."):
        cache_stats = cache.get_statistics()
        check_if_inactive_section_exists(cache_stats, False)
        check_number_of_inactive_devices(cache_stats, 0)

    with TestRun.step("Plug missing disk and stop cache."):
        second_plug_device.plug()
        time.sleep(1)
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_detached_cores():
    """
        title: Validate removing core devices from core pool.
        description: Validate that it is possible to remove core devices from core pool.
        pass_criteria:
          - No kernel error
          - All core devices are correctly added after plugging core disk.
          - All cores are successfully removed.
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 4)])
        cache_dev = devices["cache"].partitions[0]
        core_devs = devices["core"].partitions
        plug_device = devices["core"]

    with TestRun.step("Start cache and add four cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cores = []
        for d in core_devs:
            cores.append(cache.add_core(d))

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Run random writes to all CAS devices."):
        run_fio([c.path for c in cores])

    with TestRun.step("Flush dirty data from two CAS devices and verify than other two contain "
                      "dirty data."):
        for core in cores:
            if core.core_id % 2 == 0:
                core.flush_core()
                if core.get_dirty_blocks() != Size.zero():
                    TestRun.fail("Failed to flush CAS device.")
            elif core.get_dirty_blocks() == Size.zero():
                TestRun.fail("There should be dirty data on CAS device.")

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Unplug core device from system and plug it back."):
        plug_device.unplug()
        time.sleep(2)
        plug_device.plug()
        time.sleep(1)

    with TestRun.step("Verify that all cores from plugged core device are listed with "
                      "proper status."):
        for core in cores:
            if core.get_status() != CoreStatus.detached:
                TestRun.fail(f"Each core should be in detached state. "
                             f"Actual states: {casadm.list_caches().stdout}")

    with TestRun.step("Remove CAS devices from core pool."):
        casadm.remove_all_detached_cores()

    with TestRun.step("Verify that cores are no longer listed."):
        output = casadm.list_caches().stdout
        for dev in core_devs:
            if dev.path in output:
                TestRun.fail(f"CAS device is still listed in casadm list output:\n{output}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_remove_inactive_devices():
    """
        title: Validate removing inactive CAS devices.
        description: |
          Validate that it is possible to remove inactive CAS devices when there are no dirty
          cache lines associated with them and that removing CAS devices is prevented otherwise
          (unless ‘force’ option is used).
        pass_criteria:
          - No kernel error
          - Removing CAS devices without dirty data is successful.
          - Removing CAS devices with dirty data without ‘force’ option is blocked.
          - Removing CAS devices with dirty data with ‘force’ option is successful.
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 4)])
        cache_dev = devices["cache"].partitions[0]
        core_devs = devices["core"].partitions
        plug_device = devices["core"]

    with TestRun.step("Start cache and add four cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cores = []
        for d in core_devs:
            cores.append(cache.add_core(d))

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Run random writes to all CAS devices."):
        run_fio([c.path for c in cores])

    with TestRun.step("Flush dirty data from two CAS devices and verify than other two "
                      "contain dirty data."):
        for core in cores:
            if core.core_id % 2 == 0:
                core.flush_core()
                if core.get_dirty_blocks() != Size.zero():
                    TestRun.fail("Failed to flush CAS device.")
            elif core.get_dirty_blocks() == Size.zero():
                TestRun.fail("There should be dirty data on CAS device.")

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Unplug core disk."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        casadm.load_cache(cache_dev)

    with TestRun.step("Verify that all previously created CAS devices are listed with "
                      "proper status."):
        for core in cores:
            if core.get_status() != CoreStatus.inactive:
                TestRun.fail(f"Each core should be in inactive state. "
                             f"Actual states:\n{casadm.list_caches().stdout}")

    with TestRun.step("Try removing CAS devices using remove command. "
                      "Operation should be blocked and proper message displayed."):
        shuffle(cores)
        for force in [False, True]:
            for core in cores:
                try:
                    core.remove_core(force)
                    TestRun.fail(f"Removing inactive CAS device should be possible by "
                                 f"'remove-inactive' command only but it worked with 'remove' "
                                 f"command with force option set to {force}.")
                except CmdException as e:
                    TestRun.LOGGER.info(f"Remove core operation is blocked for inactive CAS device "
                                        f"as expected. Force option set to: {force}")
                    cli_messages.check_stderr_msg(
                        e.output, cli_messages.remove_inactive_core_with_remove_command)
                    output = casadm.list_caches().stdout
                    if core.path not in output:
                        TestRun.fail(
                            f"CAS device is not listed in casadm list output but it should be."
                            f"\n{output}")

    with TestRun.step("Try removing CAS devices using remove-inactive command without ‘force’ "
                      "option. Verify that for dirty CAS devices operation is blocked, proper "
                      "message is displayed and device is still listed."):
        shuffle(cores)
        for core in cores:
            try:
                dirty_blocks = core.get_dirty_blocks()
                core.remove_inactive()
                if dirty_blocks != Size.zero():
                    TestRun.fail("Removing dirty inactive CAS device should be impossible without "
                                 "force option but remove-inactive command executed without "
                                 "any error.")
                TestRun.LOGGER.info("Removing core with force option skipped for clean CAS device.")
            except CmdException as e:
                TestRun.LOGGER.info("Remove-inactive operation without force option is blocked for "
                                    "dirty CAS device as expected.")
                cli_messages.check_stderr_msg(e.output, cli_messages.remove_inactive_dirty_core)
                output = casadm.list_caches().stdout
                if core.path not in output:
                    TestRun.fail(f"CAS device is not listed in casadm list output but it should be."
                                 f"\n{output}")
                core.remove_inactive(force=True)

    with TestRun.step("Plug missing disk and stop cache."):
        plug_device.plug()
        time.sleep(1)
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_stop_cache_with_inactive_devices():
    """
        title: Validate stopping cache with inactive CAS devices.
        description: |
          Validate that cache with inactive CAS devices cannot be stopped
          unless ‘force’ option is used.
        pass_criteria:
          - No kernel error
          - Stopping cache with inactive CAS devices without ‘force’ option is blocked.
          - Stopping cache with inactive CAS devices with ‘force’ option is successful.
    """
    with TestRun.step("Prepare devices."):
        devices = prepare_devices([("cache", 1), ("core", 1)])
        cache_dev = devices["cache"].partitions[0]
        core_dev = devices["core"].partitions[0]
        plug_device = devices["core"]

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create init config file using current CAS configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Run random writes and verify that CAS device contains dirty data."):
        run_fio([core.path])
        if core.get_dirty_blocks() == Size.zero():
            TestRun.fail("There is no dirty data on core device.")

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Unplug core disk."):
        plug_device.unplug()

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Verify that previously created CAS device is listed with proper status."):
        core_status = core.get_status()
        if core_status != CoreStatus.inactive:
            TestRun.fail(f"CAS device should be in inactive state. Actual status: {core_status}.")

    with TestRun.step("Try stopping cache without ‘no data flush’ option, verify that operation "
                      "was blocked and proper message is displayed."):
        try_stop_incomplete_cache(cache)

    with TestRun.step("Stop cache with force option."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Plug missing core device."):
        plug_device.plug()
        time.sleep(1)

    with TestRun.step("Load cache."):
        cache = casadm.load_cache(cache_dev)

    with TestRun.step("Stop cache with flushing dirty data."):
        cache.stop()

    with TestRun.step("Unplug core device."):
        plug_device.unplug()

    with TestRun.step("Load cache and verify core status is inactive."):
        cache = casadm.load_cache(cache_dev)
        core_status = core.get_status()
        if core_status != CoreStatus.inactive:
            TestRun.fail(f"CAS device should be in inactive state. Actual state: {core_status}.")

    with TestRun.step("Try stopping cache without ‘no data flush’ option, verify that "
                      "operation was blocked and proper message is displayed."):
        try_stop_incomplete_cache(cache)

    with TestRun.step("Stop cache with 'no data flush' option and plug missing core device."):
        cache.stop(no_data_flush=True)
        plug_device.plug()


# Methods used in tests:
def try_stop_incomplete_cache(cache):
    try:
        cache.stop()
    except CmdException as e:
        TestRun.LOGGER.info("Stopping cache without 'no data flush' option is blocked as expected.")
        cli_messages.check_stderr_msg(e.output, cli_messages.stop_cache_incomplete)


def check_inactive_usage_stats(stats_before, stats_after, stat_name, should_be_zero):
    if should_be_zero and stats_before == Size.zero() and stats_after == Size.zero():
        TestRun.LOGGER.info(f"{stat_name} value before and after equals 0 as expected.")
    elif not should_be_zero and stats_after < stats_before:
        TestRun.LOGGER.info(f"{stat_name} is lower than before as expected.")
    else:
        TestRun.LOGGER.error(f"{stat_name} ({stats_after}) is not lower than before "
                             f"({stats_before}).")


def check_number_of_inactive_devices(stats: CacheStats, expected_num):
    inactive_core_num = stats.config_stats.inactive_core_dev
    if inactive_core_num != expected_num:
        TestRun.fail(f"There is wrong number of inactive core devices in cache statistics. "
                     f"(Expected: {expected_num}, actual: {inactive_core_num}")


def check_if_inactive_section_exists(stats, should_exist: bool = True):
    TestRun.LOGGER.info(str(stats))
    if not should_exist and hasattr(stats, "inactive_usage_stats"):
        TestRun.fail("There is an inactive section in cache usage statistics.")
    elif should_exist and not hasattr(stats, "inactive_usage_stats"):
        TestRun.fail("There is no inactive section in cache usage statistics.")


def check_amount_of_dirty_data(devices_dirty_lines_before):
    for dev in devices_dirty_lines_before:
        if dev.get_status() == CoreStatus.active and dev.get_dirty_blocks() != Size.zero():
            TestRun.fail("Amount of dirty data is not 0.")
        if dev.get_status() == CoreStatus.inactive and \
                dev.get_dirty_blocks() != devices_dirty_lines_before[dev]:
            TestRun.fail("Data from inactive cache is flushed.")


def prepare_devices(devices):
    output_disks = {}
    for dev in devices:
        disk = TestRun.disks[dev[0]]
        size = Size(1, Unit.GibiByte) if "cache" in dev else Size(400, Unit.MebiByte)
        disk.create_partitions([size for _ in range(dev[1])])
        output_disks.update({dev[0]: disk})
    return output_disks


def run_fio(targets):
    for target in targets:
        fio = (Fio()
               .create_command()
               .io_engine(IoEngine.libaio)
               .read_write(ReadWrite.randwrite)
               .direct(1)
               .size(Size(100, Unit.MebiByte))
               .sync()
               .io_depth(32)
               .target(f"{target}"))
        fio.run()
