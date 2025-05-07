#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import pytest

from api.cas import ioclass_config, casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    CleaningPolicy,
    SeqCutOffPolicy,
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.fs_tools import Filesystem, create_directory
from test_tools.udev import Udev
from test_utils.filesystem.file import File
from test_tools.os_tools import sync, DropCachesMode, drop_caches
from type_def.size import Size, Unit
from tests.io_class.io_class_common import mountpoint, ioclass_config_path


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_extension():
    """
    title: Test IO classification by file extension.
    description:|
        Test if file extension classification works properly.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on IO class rule with file extension.
    """
    iterations = 50
    ioclass_id = 1

    tested_extension = "tmp"
    wrong_extensions = ["tm", "tmpx", "txt", "t", "", "123", "tmp.xx"]

    dd_count = 10
    dd_size = Size(4, Unit.KibiByte)

    with TestRun.step("Prepare cache and core devices"):
        ioclass_config.remove_ioclass_config(ioclass_config_path)

        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(20, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_device,
            cache_mode=CacheMode.WB,
            cache_line_size=CacheLineSize.LINE_4KiB,
            force=True,
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(Filesystem.ext3)

    with TestRun.step("Add core"):
        core = casadm.add_core(cache, core_dev=core_device)

    with TestRun.step("Create and load IO class config"):
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        # Set all non-target workloads to pass-through mode to avoid caching anything
        # except files matching IO classification rules (files with extension)
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_config.DEFAULT_IO_CLASS_ID,
            eviction_priority=ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
            allocation="0.00",
            rule=ioclass_config.DEFAULT_IO_CLASS_RULE,
            ioclass_config_path=ioclass_config_path,
        )
        create_directory(path=mountpoint, parents=True)

        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"extension:{tested_extension}&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Mount core"):
        core.mount(mountpoint)

    with TestRun.step("Flush cache"):
        cache.flush_cache()

    with TestRun.step("Write to file with cached extension and check if it is properly cached"):
        for i in range(iterations):
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/test_file.{tested_extension}")
                .count(dd_count)
                .block_size(dd_size)
            )

            dd.run()
            sync()

            io_class_statistics = cache.get_io_class_statistics(io_class_id=ioclass_id)
            dirty_stat = io_class_statistics.usage_stats.dirty
            if dirty_stat.get_value(Unit.Blocks4096) != (i + 1) * dd_count:
                TestRun.LOGGER.error(
                    f"Wrong amount of dirty data occurred in stats: ({dirty_stat})."
                )

    with TestRun.step("Flush cache"):
        cache.flush_cache()

    with TestRun.step("Write to file with not cached extension and check if it is not cached"):
        for wrong_extension in wrong_extensions:
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/test_file.{wrong_extension}")
                .count(dd_count)
                .block_size(dd_size)
            )
            dd.run()
            sync()

            io_class_statistics = cache.get_io_class_statistics(io_class_id=ioclass_id)
            dirty_stat = io_class_statistics.usage_stats.dirty
            if dirty_stat.get_value(Unit.Blocks4096) != 0:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty_stat}).")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_name_prefix():
    """
    title: Test IO classification by file name prefix.
    description:|
        Test if file name prefix classification works properly.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on IO class rule with file name prefix.
    """
    ioclass_id = 1

    cached_files = ["test", "test.txt", "test1", "test1.txt"]
    not_cached_files = ["file1", "file2", "file4", "file5", "tes"]

    dd_count = 10
    dd_size = Size(4, Unit.KibiByte)

    with TestRun.step("Prepare cache and core devices"):
        ioclass_config.remove_ioclass_config(ioclass_config_path)

        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(20, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_device,
            cache_mode=CacheMode.WB,
            cache_line_size=CacheLineSize.LINE_4KiB,
            force=True,
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(Filesystem.ext3)

    with TestRun.step("Add core"):
        core = casadm.add_core(cache, core_dev=core_device)

    with TestRun.step("Create and load IO class config"):
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        # Set all non-target workloads to pass-through mode to avoid caching anything
        # except files matching IO classification rules (files with prefix)
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_config.DEFAULT_IO_CLASS_ID,
            eviction_priority=ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
            allocation="0.00",
            rule=ioclass_config.DEFAULT_IO_CLASS_RULE,
            ioclass_config_path=ioclass_config_path,
        )
        create_directory(path=mountpoint, parents=True)

        # Enables file with specified prefix to be cached
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule="file_name_prefix:test&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Purge cache and reset statistics"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step("Mount core"):
        core.mount(mountpoint)

        current_occupancy = cache.get_occupancy()
        if current_occupancy != Size.zero():
            TestRun.fail(
                "Current occupancy value is not valid.\n"
                f"Expected occupancy: 0\n"
                f"Actual occupancy: {str(current_occupancy)})"
            )

        previous_occupancy = current_occupancy

    # Check if files with proper prefix are cached
    with TestRun.step("Write files which are supposed to be cached and check if they are cached"):
        for cached_file in cached_files:
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/{cached_file}")
                .count(dd_count)
                .block_size(Size(4, Unit.KibiByte))
            )
            dd.run()

            sync()

            current_occupancy = cache.get_occupancy()
            expected_occupancy = previous_occupancy + (Size(4, Unit.KibiByte) * dd_count)
            if current_occupancy != expected_occupancy:
                TestRun.fail(
                    "Current occupancy value is not valid.\n"
                    f"Expected occupancy value: {str(expected_occupancy)}\n"
                    f"Actual occupancy value: {str(current_occupancy)})"
                )

            previous_occupancy = current_occupancy

    with TestRun.step("Flush cache"):
        cache.flush_cache()

    # Check if file with improper extension is not cached
    with TestRun.step(
        "Write files which are not supposed to be cached and check if they are not cached."
    ):
        for not_cached_file in not_cached_files:
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/{not_cached_file}")
                .count(dd_count)
                .block_size(dd_size)
            )
            dd.run()

            sync()
            current_occupancy = cache.get_occupancy()
            if current_occupancy != previous_occupancy:
                TestRun.fail(
                    "Current occupancy value is not valid.\n"
                    f"Expected occupancy value: {str(previous_occupancy)}\n "
                    f"Actual occupancy value: {str(current_occupancy)})"
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_extension_preexisting_filesystem():
    """
    title: Test IO classification by file extension with preexisting files on core device.
    description: |
        Test if file extension classification works properly when there are preexisting files.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on IO class rule with file extension
        after mounting core device.
    """
    ioclass_id = 1

    extensions = ["tmp", "tm", "out", "txt", "log", "123"]

    dd_size = Size(4, Unit.KibiByte)
    dd_count = 10

    with TestRun.step("Prepare cache and core devices"):
        ioclass_config.remove_ioclass_config(ioclass_config_path)

        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(20, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_device,
            cache_mode=CacheMode.WB,
            cache_line_size=CacheLineSize.LINE_4KiB,
            force=True,
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Prepare preexisting files on core device"):
        core_device.create_filesystem(Filesystem.ext3)
        core_device.mount(mountpoint)

        for extension in extensions:
            (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/test_file.{extension}")
                .count(dd_count)
                .block_size(dd_size)
                .run()
            )

        core_device.unmount()

    with TestRun.step("Create and load IO class configs"):
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        # Set all non-target workloads to pass-through mode to avoid caching anything
        # except files matching IO classification rules (files with extensions)
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_config.DEFAULT_IO_CLASS_ID,
            eviction_priority=ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
            allocation="0.00",
            rule=ioclass_config.DEFAULT_IO_CLASS_RULE,
            ioclass_config_path=ioclass_config_path,
        )
        create_directory(path=mountpoint, parents=True)

        rule = "|".join([f"extension:{extension}" for extension in extensions])
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"{rule}&done",
            ioclass_config_path=ioclass_config_path,
        )

    with TestRun.step("Add device with preexisting data as a core"):
        core = casadm.add_core(cache, core_dev=core_device)

    with TestRun.step("Load IO class config"):
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Mount core and flush cache"):
        core.mount(mountpoint)
        cache.flush_cache()

    with TestRun.step("Write to file with cached extension and check if they are cached"):
        for index, extension in enumerate(extensions):
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/test_file.{extension}")
                .count(dd_count)
                .block_size(dd_size)
            )
            dd.run()
            sync()

            io_class_statistics = cache.get_io_class_statistics(io_class_id=ioclass_id)
            dirty_stat = io_class_statistics.usage_stats.dirty
            if dirty_stat.get_value(Unit.Blocks4096) != (index + 1) * dd_count:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty_stat}).")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_file_offset():
    """
    title: Test IO classification by file offset.
    description:|
        Test if file offset classification works properly.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on IO class rule with file offset.
    """
    ioclass_id = 1
    iterations = 100

    min_cached_offset = 16384
    max_cached_offset = 65536

    dd_size = Size(4, Unit.KibiByte)
    blocks4096 = Unit.Blocks4096.get_value()
    dd_count = 1

    with TestRun.step("Prepare cache and core devices"):
        ioclass_config.remove_ioclass_config(ioclass_config_path)

        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(20, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_dev=cache_device,
            cache_mode=CacheMode.WB,
            cache_line_size=CacheLineSize.LINE_4KiB,
            force=True,
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(Filesystem.ext3)

    with TestRun.step("Add core"):
        core = casadm.add_core(cache=cache, core_dev=core_device)

    with TestRun.step("Create and load IO class configs"):
        ioclass_config.create_ioclass_config(
            add_default_rule=False, ioclass_config_path=ioclass_config_path
        )
        # Set all non-target workloads to pass-through mode to avoid caching anything
        # except files matching IO classification rules (specified offset)
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_config.DEFAULT_IO_CLASS_ID,
            eviction_priority=ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
            allocation="0.00",
            rule=ioclass_config.DEFAULT_IO_CLASS_RULE,
            ioclass_config_path=ioclass_config_path,
        )
        create_directory(path=mountpoint, parents=True)

        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_offset:gt:{min_cached_offset}&file_offset:lt:{max_cached_offset}&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Mount core"):
        core.mount(mountpoint)

    with TestRun.step("Flush cache"):
        cache.flush_cache()

    with TestRun.step("Write to file within cached offset range and check if it is cached."):
        # Since ioclass rule consists of strict inequalities, 'seek' can't be set to first
        # nor last sector

        min_seek = int((min_cached_offset + blocks4096) / blocks4096)
        max_seek = int((max_cached_offset - min_cached_offset - blocks4096) / blocks4096)

        for i in range(iterations):
            file_offset = random.choice(range(min_seek, max_seek))
            dd = (
                Dd()
                .input("/dev/zero")
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

    with TestRun.step("Write to file outside of cached offset range and check if it is not cached"):
        min_seek = 0
        max_seek = int(min_cached_offset / blocks4096)

        for i in range(iterations):
            file_offset = random.choice(range(min_seek, max_seek))
            dd = (
                Dd()
                .input("/dev/zero")
                .output(f"{mountpoint}/tmp_file")
                .count(dd_count)
                .block_size(dd_size)
                .seek(file_offset)
            )
            dd.run()
            sync()

            io_class_statistics = cache.get_io_class_statistics(io_class_id=ioclass_id)
            dirty_stat = io_class_statistics.usage_stats.dirty
            if dirty_stat.get_value(Unit.Blocks4096) != 0:
                TestRun.LOGGER.error(f"Inappropriately cached offset: {file_offset}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_file_size(filesystem: Filesystem):
    """
    title: Test IO classification by file size.
    description:|
        Test if file size classification works properly.
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
        base_size - Size(1, Unit.Blocks4096): 2,
        base_size + Size(1, Unit.Blocks4096): 3,
        base_size / 2: 4,
        base_size / 2 - Size(1, Unit.Blocks4096): 4,
        base_size / 2 + Size(1, Unit.Blocks4096): 2,
        base_size * 2: 5,
        base_size * 2 - Size(1, Unit.Blocks4096): 3,
        base_size * 2 + Size(1, Unit.Blocks4096): 5,
    }

    with TestRun.step("Prepare cache and core devices"):
        ioclass_config.remove_ioclass_config(ioclass_config_path)

        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        core_device.create_partitions([Size(20, Unit.GibiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache"):
        cache = casadm.start_cache(
            cache_device,
            cache_mode=CacheMode.WB,
            cache_line_size=CacheLineSize.LINE_4KiB,
            force=True,
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Disable cleaning policy and sequential cutoff"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)

    with TestRun.step("Create filesystem on core device"):
        core_device.create_filesystem(fs_type=filesystem)

    with TestRun.step("Add core"):
        core = casadm.add_core(cache, core_dev=core_device)

    with TestRun.step("Create and load IO class config"):
        ioclass_config.create_ioclass_config(
            add_default_rule=True, ioclass_config_path=ioclass_config_path
        )
        create_directory(path=mountpoint, parents=True)
        load_file_size_io_classes(cache, base_size)

    with TestRun.step("Mount core"):
        core.mount(mountpoint)
        sync()

    with TestRun.step("Create files belonging to different IO classes (classification by writes)"):
        test_files = []
        for io_size, ioclass_id in size_to_class.items():
            cache_stats = cache.get_io_class_statistics(io_class_id=ioclass_id)
            cache_occupancy_before = cache_stats.usage_stats.occupancy

            file_path = f"{mountpoint}/test_file_{io_size.get_value()}"
            dd = (
                Dd().input("/dev/zero").output(file_path).oflag("sync").block_size(io_size).count(1)
            )
            dd.run()

            sync()
            drop_caches(DropCachesMode.ALL)

            cache_stats = cache.get_io_class_statistics(io_class_id=ioclass_id)
            cache_occupancy_after = cache_stats.usage_stats.occupancy
            expected_occupancy = cache_occupancy_before + io_size

            if cache_occupancy_after != expected_occupancy:
                TestRun.fail(
                    "Wrong amount of cached data occurred in stats\n"
                    f"Expected amount of cached data: {expected_occupancy}\n"
                    f"Actual amount of cached data:{cache_occupancy_after}"
                )
            test_files.append(File(file_path).refresh_item())

        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Purge cache"):
        cache.purge_cache()

    with TestRun.step("Restore IO class configuration"):
        ioclass_config.create_ioclass_config(True, ioclass_config_path)
        load_file_size_io_classes(cache, base_size)

    with TestRun.step("Read files belonging to different IO classes (classification by reads)"):
        # CAS device should be unmounted and mounted because data can be sometimes still cached by
        # OS cache so occupancy statistics will not match
        core.unmount()
        core.mount(mountpoint)

        for file in test_files:
            ioclass_id = size_to_class[file.size]

            cache_stats = cache.get_io_class_statistics(io_class_id=ioclass_id)
            cache_occupancy_before = cache_stats.usage_stats.occupancy

            dd = Dd().input(file.full_path).output("/dev/null").block_size(file.size)
            dd.run()

            sync()
            drop_caches(DropCachesMode.ALL)

            cache_stats = cache.get_io_class_statistics(io_class_id=ioclass_id)
            cache_occupancy_after = cache_stats.usage_stats.occupancy
            expected_occupancy = cache_occupancy_before + file.size

            actual_blocks = cache_occupancy_after.get_value(Unit.Blocks4096)
            expected_blocks = expected_occupancy.get_value(Unit.Blocks4096)
            if actual_blocks != expected_blocks:
                TestRun.fail(
                    "Wrong amount of cached blocks occurred in IO class stat after "
                    "reclassification !\n"
                    f"Expected amount of cached blocks: {actual_blocks}\n"
                    f"Actual amount of cached blocks: {expected_blocks}"
                )

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
