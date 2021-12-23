#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random

import pytest

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.file import File
from test_utils.os_utils import sync, DropCachesMode, drop_caches
from test_utils.size import Size, Unit
from tests.io_class.io_class_common import mountpoint, prepare, ioclass_config_path


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_extension():
    """
        title: Test IO classification by file extension.
        description: Test if file extension classification works properly.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on IO class rule with file extension.
    """
    iterations = 50
    ioclass_id = 1
    tested_extension = "tmp"
    wrong_extensions = ["tm", "tmpx", "txt", "t", "", "123", "tmp.xx"]
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10
    dd = (
        Dd().input("/dev/zero")
            .output(f"{mountpoint}/test_file.{tested_extension}")
            .count(dd_count)
            .block_size(dd_size)
    )

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Create and load IO class config."):
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"extension:{tested_extension}&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}."):
        core.create_filesystem(Filesystem.ext3)
        core.mount(mountpoint)

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    with TestRun.step(f"Write to file with cached extension and check if it is properly cached."):
        for i in range(iterations):
            dd.run()
            sync()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != (i + 1) * dd_count:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty}).")

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    with TestRun.step(f"Write to file with not cached extension and check if it is not cached."):
        for ext in wrong_extensions:
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/test_file.{ext}")
                    .count(dd_count)
                    .block_size(dd_size)
            )
            dd.run()
            sync()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != 0:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty}).")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_name_prefix():
    """
        title: Test IO classification by file name prefix.
        description: Test if file name prefix classification works properly.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on IO class rule with file name prefix.
    """

    ioclass_id = 1
    cached_files = ["test", "test.txt", "test1", "test1.txt"]
    not_cached_files = ["file1", "file2", "file4", "file5", "tes"]
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Create and load IO class config."):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

        # Avoid caching anything else than files with specified prefix
        ioclass_config.add_ioclass(
            ioclass_id=0,
            eviction_priority=255,
            allocation="0.00",
            rule=f"unclassified",
            ioclass_config_path=ioclass_config_path,
        )
        # Enables file with specified prefix to be cached
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_name_prefix:test&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        previous_occupancy = cache.get_occupancy()

        core.create_filesystem(Filesystem.ext3)
        core.mount(mountpoint)

        current_occupancy = cache.get_occupancy()
        if previous_occupancy.get_value() > current_occupancy.get_value():
            TestRun.fail(f"Current occupancy ({str(current_occupancy)}) is lower "
                         f"than before ({str(previous_occupancy)}).")

        # Filesystem creation caused metadata IO which is not supposed
        # to be cached

    # Check if files with proper prefix are cached
    with TestRun.step(f"Write files which are supposed to be cached and check "
                      f"if they are cached."):
        for f in cached_files:
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/{f}")
                    .count(dd_count)
                    .block_size(dd_size)
            )
            dd.run()
            sync()
            current_occupancy = cache.get_occupancy()
            expected_occupancy = previous_occupancy + (dd_size * dd_count)
            if current_occupancy != expected_occupancy:
                TestRun.fail(f"Current occupancy value is not valid. "
                             f"(Expected: {str(expected_occupancy)}, "
                             f"actual: {str(current_occupancy)})")
            previous_occupancy = current_occupancy

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    # Check if file with improper extension is not cached
    with TestRun.step(f"Write files which are not supposed to be cached and check if "
                      f"they are not cached."):
        for f in not_cached_files:
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/{f}")
                    .count(dd_count)
                    .block_size(dd_size)
            )
            dd.run()
            sync()
            current_occupancy = cache.get_occupancy()
            if current_occupancy != previous_occupancy:
                TestRun.fail(f"Current occupancy value is not valid. "
                             f"(Expected: {str(previous_occupancy)}, "
                             f"actual: {str(current_occupancy)})")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_extension_preexisting_filesystem():
    """
        title: Test IO classification by file extension with preexisting filesystem on core device.
        description: |
          Test if file extension classification works properly when there is an existing
          filesystem on core device.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on IO class rule with file extension
            after mounting core device.
    """
    ioclass_id = 1
    extensions = ["tmp", "tm", "out", "txt", "log", "123"]
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10

    with TestRun.step("Prepare cache and core devices."):
        cache, core = prepare()

    with TestRun.step(f"Prepare files on raw block device."):
        casadm.remove_core(cache.cache_id, core_id=core.core_id)
        core.core_device.create_filesystem(Filesystem.ext3)
        core.core_device.mount(mountpoint)

        for ext in extensions:
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/test_file.{ext}")
                    .count(dd_count)
                    .block_size(dd_size)
            )
            dd.run()
        core.core_device.unmount()

    with TestRun.step("Create IO class config."):
        rule = "|".join([f"extension:{ext}" for ext in extensions])
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"{rule}&done",
            ioclass_config_path=ioclass_config_path,
        )

    with TestRun.step(f"Add device with preexisting data as a core."):
        core = casadm.add_core(cache, core_dev=core.core_device)

    with TestRun.step("Load IO class config."):
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Mount core and flush cache."):
        core.mount(mountpoint)
        cache.flush_cache()

    with TestRun.step(f"Write to file with cached extension and check if they are cached."):
        for ext in extensions:
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/test_file.{ext}")
                    .count(dd_count)
                    .block_size(dd_size)
            )
            dd.run()
            sync()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != (extensions.index(ext) + 1) * dd_count:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty}).")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_offset():
    """
        title: Test IO classification by file offset.
        description: Test if file offset classification works properly.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on IO class rule with file offset.
    """
    ioclass_id = 1
    iterations = 100
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 1
    min_cached_offset = 16384
    max_cached_offset = 65536

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Create and load IO class config file."):
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_offset:gt:{min_cached_offset}&file_offset:lt:{max_cached_offset}&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}."):
        core.create_filesystem(Filesystem.ext3)
        core.mount(mountpoint)

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    with TestRun.step("Write to file within cached offset range and check if it is cached."):
        # Since ioclass rule consists of strict inequalities, 'seek' can't be set to first
        # nor last sector
        min_seek = int((min_cached_offset + Unit.Blocks4096.value) / Unit.Blocks4096.value)
        max_seek = int(
            (max_cached_offset - min_cached_offset - Unit.Blocks4096.value)
            / Unit.Blocks4096.value
        )

        for i in range(iterations):
            file_offset = random.choice(range(min_seek, max_seek))
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/tmp_file")
                    .count(dd_count)
                    .block_size(dd_size)
                    .seek(file_offset)
            )
            dd.run()
            sync()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != 1:
                TestRun.LOGGER.error(f"Offset not cached: {file_offset}")
            cache.flush_cache()

    with TestRun.step(
            "Write to file outside of cached offset range and check if it is not cached."):
        min_seek = 0
        max_seek = int(min_cached_offset / Unit.Blocks4096.value)
        TestRun.LOGGER.info(f"Writing to file outside of cached offset range")
        for i in range(iterations):
            file_offset = random.choice(range(min_seek, max_seek))
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{mountpoint}/tmp_file")
                    .count(dd_count)
                    .block_size(dd_size)
                    .seek(file_offset)
            )
            dd.run()
            sync()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != 0:
                TestRun.LOGGER.error(f"Inappropriately cached offset: {file_offset}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_file_size(filesystem):
    """
        title: Test IO classification by file size.
        description: Test if file size classification works properly.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on IO class rule with file size.
    """

    # File size IO class rules are configured in a way that each tested file size is unambiguously
    # classified.
    # Firstly write operations are tested (creation of files), secondly read operations.

    base_size = Size(random.randint(50, 1000) * 2, Unit.Blocks4096)
    size_to_class = {
        base_size: 1,
        base_size - Unit.Blocks4096: 2,
        base_size + Unit.Blocks4096: 3,
        base_size / 2: 4,
        base_size / 2 - Unit.Blocks4096: 4,
        base_size / 2 + Unit.Blocks4096: 2,
        base_size * 2: 5,
        base_size * 2 - Unit.Blocks4096: 3,
        base_size * 2 + Unit.Blocks4096: 5,
    }

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare(default_allocation="1.00")

    with TestRun.step("Prepare and load IO class config."):
        load_file_size_io_classes(cache, base_size)

    with TestRun.step(f"Prepare {filesystem.name} filesystem and mount {core.path} "
                      f"at {mountpoint}."):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Create files belonging to different IO classes (classification by writes)."):
        test_files = []
        for size, ioclass_id in size_to_class.items():
            occupancy_before = cache.get_io_class_statistics(
                io_class_id=ioclass_id).usage_stats.occupancy
            file_path = f"{mountpoint}/test_file_{size.get_value()}"
            Dd().input("/dev/zero").output(file_path).oflag("sync").block_size(size).count(1).run()
            sync()
            drop_caches(DropCachesMode.ALL)
            occupancy_after = cache.get_io_class_statistics(
                io_class_id=ioclass_id).usage_stats.occupancy
            if occupancy_after != occupancy_before + size:
                TestRun.fail("File not cached properly!\n"
                             f"Expected {occupancy_before + size}\n"
                             f"Actual {occupancy_after}")
            test_files.append(File(file_path).refresh_item())
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Move all files to 'unclassified' IO class."):
        ioclass_config.remove_ioclass_config(ioclass_config_path=ioclass_config_path)
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        ioclass_config.add_ioclass(
            ioclass_id=0,
            eviction_priority=22,
            allocation="1.00",
            rule="unclassified",
            ioclass_config_path=ioclass_config_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=6,
            eviction_priority=1,
            allocation="0.00",
            rule=f"metadata",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)
        occupancy_before = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        for file in test_files:
            Dd().input(file.full_path).output("/dev/null").block_size(file.size).run()
            sync()
            drop_caches(DropCachesMode.ALL)
            occupancy_after = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
            occupancy_expected = occupancy_before + file.size
            if occupancy_after != occupancy_expected:
                TestRun.fail("File not reclassified properly!\n"
                             f"Expected {occupancy_expected}\n"
                             f"Actual {occupancy_after}")
            occupancy_before = occupancy_after
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Restore IO class configuration."):
        ioclass_config.remove_ioclass_config(ioclass_config_path=ioclass_config_path)
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        ioclass_config.add_ioclass(
            ioclass_id=0,
            eviction_priority=22,
            allocation="1.00",
            rule="unclassified",
            ioclass_config_path=ioclass_config_path,
        )
        load_file_size_io_classes(cache, base_size)

    with TestRun.step("Read files belonging to different IO classes (classification by reads)."):
        # CAS device should be unmounted and mounted because data can be sometimes still cached by
        # OS cache so occupancy statistics will not match
        core.unmount()
        core.mount(mountpoint)
        for file in test_files:
            ioclass_id = size_to_class[file.size]
            occupancy_before = cache.get_io_class_statistics(
                io_class_id=ioclass_id).usage_stats.occupancy
            Dd().input(file.full_path).output("/dev/null").block_size(file.size).run()
            sync()
            drop_caches(DropCachesMode.ALL)
            occupancy_after = cache.get_io_class_statistics(
                io_class_id=ioclass_id).usage_stats.occupancy
            actual_blocks = occupancy_after.get_value(Unit.Blocks4096)
            expected_blocks = (occupancy_before + file.size).get_value(Unit.Blocks4096)
            if actual_blocks != expected_blocks:
                TestRun.fail("File not reclassified properly!\n"
                             f"Expected {occupancy_before + file.size}\n"
                             f"Actual {occupancy_after}")
        sync()
        drop_caches(DropCachesMode.ALL)


def load_file_size_io_classes(cache, base_size):
    # IO class order intentional, do not change
    base_size_bytes = int(base_size.get_value(Unit.Byte))
    ioclass_config.add_ioclass(
        ioclass_id=6,
        eviction_priority=1,
        allocation="0.00",
        rule=f"metadata",
        ioclass_config_path=ioclass_config_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=1,
        eviction_priority=1,
        allocation="1.00",
        rule=f"file_size:eq:{base_size_bytes}",
        ioclass_config_path=ioclass_config_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=2,
        eviction_priority=1,
        allocation="1.00",
        rule=f"file_size:lt:{base_size_bytes}",
        ioclass_config_path=ioclass_config_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=3,
        eviction_priority=1,
        allocation="1.00",
        rule=f"file_size:gt:{base_size_bytes}",
        ioclass_config_path=ioclass_config_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=4,
        eviction_priority=1,
        allocation="1.00",
        rule=f"file_size:le:{int(base_size_bytes / 2)}",
        ioclass_config_path=ioclass_config_path,
    )
    ioclass_config.add_ioclass(
        ioclass_id=5,
        eviction_priority=1,
        allocation="1.00",
        rule=f"file_size:ge:{2 * base_size_bytes}",
        ioclass_config_path=ioclass_config_path,
    )

    casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)
