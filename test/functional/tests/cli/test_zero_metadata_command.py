#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import time
from datetime import timedelta

import pytest

from api.cas import casadm, cli_messages, cli
from api.cas.cache_config import CacheMode, CleaningPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.disk_utils import get_device_filesystem_type, Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.disk_finder import get_system_disks
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_zero_metadata_negative_cases():
    """
        title: Test for '--zero-metadata' negative cases.
        description: |
          Test for '--zero-metadata' scenarios with expected failures.
        pass_criteria:
          - Zeroing metadata without '--force' failed when run on cache.
          - Zeroing metadata with '--force' failed when run on cache.
          - Zeroing metadata failed when run on system drive.
          - Load cache command failed after successfully zeroing metadata on the cache device.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_dev, core_dev, cache_disk = prepare_devices()

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, force=True)

    with TestRun.step("Try to zero metadata and validate error message."):
        try:
            casadm.zero_metadata(cache_dev)
            TestRun.LOGGER.error("Zeroing metadata should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.unavailable_device)

    with TestRun.step("Try to zero metadata with '--force' option and validate error message."):
        try:
            casadm.zero_metadata(cache_dev, force=True)
            TestRun.LOGGER.error("Zeroing metadata with '--force' option should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.unavailable_device)

    with TestRun.step("Try to zeroing metadata on system disk."):
        os_disks = get_system_disks()
        for os_disk in os_disks:
            output = TestRun.executor.run(cli.zero_metadata_cmd(str(os_disk)))
            if output.exit_code != 0:
                cli_messages.check_stderr_msg(output, cli_messages.error_handling)
            else:
                TestRun.LOGGER.error("Zeroing metadata should fail!")

    with TestRun.step("Stop cache."):
        casadm.stop_all_caches()

    with TestRun.step("Zeroing metadata."):
        try:
            casadm.zero_metadata(cache_dev)
            TestRun.LOGGER.info("Zeroing metadata successful!")
        except CmdException as e:
            TestRun.LOGGER.error(f"Zeroing metadata should work for cache device after stopping "
                                 f"cache! Error message: {e.output}")

    with TestRun.step("Load cache."):
        try:
            cache = casadm.load_cache(cache_dev)
            TestRun.LOGGER.error("Loading cache should fail.")
        except CmdException:
            TestRun.LOGGER.info("Loading cache failed as expected.")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_zero_metadata_filesystem(filesystem):
    """
        title: Test for '--zero-metadata' and filesystem.
        description: |
          Test for '--zero-metadata' on drive with filesystem.
        pass_criteria:
          - Zeroing metadata on device with filesystem failed and not removed filesystem.
          - Zeroing metadata on mounted device failed.
    """
    mount_point = "/mnt"
    with TestRun.step("Prepare devices."):
        cache_dev, core_disk, cache_disk = prepare_devices()

    with TestRun.step("Create filesystem on core device."):
        core_disk.create_filesystem(filesystem)

    with TestRun.step("Start cache and add core."):
        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_disk)

    with TestRun.step("Zeroing metadata on core device and validating filesystem"):
        try:
            casadm.zero_metadata(core)
            TestRun.LOGGER.error("Zeroing metadata should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.no_cas_metadata)

        file_system = get_device_filesystem_type(core.get_device_id())

        if file_system != filesystem:
            TestRun.LOGGER.error(f"Incorrect filesystem: {file_system}; expected: {filesystem}")

    with TestRun.step("Mount core."):
        core.mount(mount_point)

    with TestRun.step("Zeroing metadata on mounted core device and validate result"):
        try:
            casadm.zero_metadata(core)
            TestRun.LOGGER.error("Zeroing metadata should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.unavailable_device)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_zero_metadata_dirty_data():
    """
        title: Test for '--zero-metadata' and dirty data scenario.
        description: |
          Test for '--zero-metadata' with and without 'force' option if there are dirty data
          on cache.
        pass_criteria:
          - Zeroing metadata without force failed on cache with dirty data.
          - Zeroing metadata with force ran successfully on cache with dirty data.
          - Cache started successfully after zeroing metadata on cache with dirty data.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_dev, core_disk, cache_disk = prepare_devices()

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, CacheMode.WB, force=True)
        core = cache.add_core(core_disk)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Run workload on CAS"):
        fio_run_fill = Fio().create_command()
        fio_run_fill.io_engine(IoEngine.libaio)
        fio_run_fill.direct()
        fio_run_fill.read_write(ReadWrite.randwrite)
        fio_run_fill.io_depth(16)
        fio_run_fill.block_size(Size(1, Unit.MebiByte))
        fio_run_fill.target(core.path)
        fio_run_fill.run_time(timedelta(seconds=5))
        fio_run_fill.time_based()
        fio_run_fill.run()

    with TestRun.step("Stop cache without flushing dirty data."):
        cache.stop(no_data_flush=True)

    with TestRun.step("Start cache (expect to fail)."):
        try:
            cache = casadm.start_cache(cache_dev, CacheMode.WB)
        except CmdException:
            TestRun.LOGGER.info("Start cache failed as expected.")

    with TestRun.step("Zeroing metadata on CAS device without force"):
        try:
            casadm.zero_metadata(cache_dev)
            TestRun.LOGGER.error("Zeroing metadata without force should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.cache_dirty_data)

    with TestRun.step("Zeroing metadata on cache device with force"):
        try:
            casadm.zero_metadata(cache_dev, force=True)
            TestRun.LOGGER.info("Zeroing metadata with force successful!")
        except CmdException as e:
            TestRun.LOGGER.error(f"Zeroing metadata with force should work for cache device!"
                                 f"Error message: {e.output}")

        with TestRun.step("Start cache without 'force' option."):
            try:
                cache = casadm.start_cache(cache_dev, CacheMode.WB)
                TestRun.LOGGER.info("Cache started successfully.")
            except CmdException:
                TestRun.LOGGER.error("Start cache failed.")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_zero_metadata_dirty_shutdown():
    """
        title: Test for '--zero-metadata' and dirty shutdown scenario.
        description: |
          Test for '--zero-metadata' with and without 'force' option on cache which had been dirty
          shut down before.
        pass_criteria:
          - Zeroing metadata without force failed on cache after dirty shutdown.
          - Zeroing metadata with force ran successfully on cache after dirty shutdown.
          - Cache started successfully after dirty shutdown and zeroing metadata on cache.
    """
    with TestRun.step("Prepare cache and core devices."):
        cache_dev, core_disk, cache_disk = prepare_devices()

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_dev, CacheMode.WT, force=True)
        core = cache.add_core(core_disk)

    with TestRun.step("Unplug cache device."):
        cache_disk.unplug()

    with TestRun.step("Stop cache without flush."):
        try:
            cache.stop(no_data_flush=True)
        except CmdException:
            TestRun.LOGGER.info("This could ended with error (expected)")

    with TestRun.step("Plug cache device."):
        cache_disk.plug()
        time.sleep(1)

    with TestRun.step("Start cache (expect to fail)."):
        try:
            cache = casadm.start_cache(cache_dev, CacheMode.WT)
            TestRun.LOGGER.error("Starting cache should fail!")
        except CmdException:
            TestRun.LOGGER.info("Start cache failed as expected.")

    with TestRun.step("Zeroing metadata on CAS device without force"):
        try:
            casadm.zero_metadata(cache_dev)
            TestRun.LOGGER.error("Zeroing metadata without force should fail!")
        except CmdException as e:
            cli_messages.check_stderr_msg(e.output, cli_messages.cache_dirty_shutdown)

    with TestRun.step("Zeroing metadata on cache device with force"):
        try:
            casadm.zero_metadata(cache_dev, force=True)
            TestRun.LOGGER.info("Zeroing metadata with force successful!")
        except CmdException as e:
            TestRun.LOGGER.error(f"Zeroing metadata with force should work for cache device!"
                                 f"Error message: {e.output}")

    with TestRun.step("Start cache."):
        try:
            cache = casadm.start_cache(cache_dev, CacheMode.WT)
            TestRun.LOGGER.info("Cache started successfully.")
        except CmdException:
            TestRun.LOGGER.error("Start cache failed.")


def prepare_devices():
    cache_disk = TestRun.disks['cache']
    cache_disk.create_partitions([Size(100, Unit.MebiByte)])
    cache_part = cache_disk.partitions[0]
    core_disk = TestRun.disks['core']
    core_disk.create_partitions([Size(5, Unit.GibiByte)])

    return cache_part, core_disk, cache_disk
