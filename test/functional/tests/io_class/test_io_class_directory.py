#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
from datetime import datetime
import time

import pytest

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.filesystem.directory import Directory
from test_utils.filesystem.file import File
from test_utils.os_utils import drop_caches, DropCachesMode, sync, Udev
from test_utils.size import Size, Unit
from tests.io_class.io_class_common import mountpoint, prepare, ioclass_config_path


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_directory_depth(filesystem):
    """
        title: Test IO classification by directory.
        description: |
          Test if directory classification works properly for deeply nested directories for read and
          write operations.
        pass_criteria:
          - No kernel bug.
          - Read and write operations to directories are classified properly.
    """
    base_dir_path = f"{mountpoint}/base_dir"

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step(f"Prepare {filesystem.name} filesystem and mount {core.path} "
                      f"at {mountpoint}."):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step(f"Create the base directory: {base_dir_path}."):
        fs_utils.create_directory(base_dir_path)

    with TestRun.step(f"Create a nested directory."):
        nested_dir_path = base_dir_path
        random_depth = random.randint(40, 80)
        for i in range(random_depth):
            nested_dir_path += f"/dir_{i}"
        fs_utils.create_directory(path=nested_dir_path, parents=True)

    # Test classification in nested dir by reading a previously unclassified file
    with TestRun.step("Create the first file in the nested directory."):
        test_file_1 = File(f"{nested_dir_path}/test_file_1")
        dd = (
            Dd().input("/dev/urandom")
                .output(test_file_1.full_path)
                .count(random.randint(1, 200))
                .block_size(Size(1, Unit.MebiByte))
        )
        dd.run()
        sync()
        drop_caches(DropCachesMode.ALL)
        test_file_1.refresh_item()

    with TestRun.step("Load IO class config."):
        ioclass_id = random.randint(1, ioclass_config.MAX_IO_CLASS_ID)
        # directory IO class
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{base_dir_path}",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Read the file in the nested directory"):
        base_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        dd = (
            Dd().input(test_file_1.full_path)
                .output("/dev/null")
                .block_size(Size(1, Unit.MebiByte))
        )
        dd.run()

    with TestRun.step("Check occupancy after creating the file."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        if new_occupancy != base_occupancy + test_file_1.size:
            TestRun.LOGGER.error("Wrong occupancy after reading file!\n"
                                 f"Expected: {base_occupancy + test_file_1.size}, "
                                 f"actual: {new_occupancy}")

    # Test classification in nested dir by creating a file
    with TestRun.step("Create the second file in the nested directory"):
        base_occupancy = new_occupancy
        test_file_2 = File(f"{nested_dir_path}/test_file_2")
        dd = (
            Dd().input("/dev/urandom")
                .output(test_file_2.full_path)
                .count(random.randint(25600, 51200))  # 100MB to 200MB
                .block_size(Size(1, Unit.Blocks4096))
        )
        dd.run()
        sync()
        drop_caches(DropCachesMode.ALL)
        test_file_2.refresh_item()

    with TestRun.step("Check occupancy after creating the second file."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        expected_occpuancy = (base_occupancy + test_file_2.size).set_unit(Unit.Blocks4096)
        if new_occupancy != base_occupancy + test_file_2.size:
            TestRun.LOGGER.error("Wrong occupancy after creating file!\n"
                                 f"Expected: {expected_occpuancy}, "
                                 f"actual: {new_occupancy}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_directory_file_operations(filesystem):
    """
        title: Test IO classification by file operations.
        description: |
          Test if directory classification works properly after file operations like move or rename.
        pass_criteria:
          - No kernel bug.
          - The operations themselves should not cause reclassification but IO after those
            operations should be reclassified to proper IO class.
    """

    test_dir_path = f"{mountpoint}/test_dir"
    nested_dir_path = f"{test_dir_path}/nested_dir"
    dd_blocks = random.randint(5, 50)

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare(default_allocation="1.00")
        Udev.disable()

    with TestRun.step("Create and load IO class config file."):
        ioclass_id = random.randint(2, ioclass_config.MAX_IO_CLASS_ID)
        ioclass_config.add_ioclass(ioclass_id=1,
                                   eviction_priority=1,
                                   allocation="1.00",
                                   rule="metadata",
                                   ioclass_config_path=ioclass_config_path)
        # directory IO class
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{test_dir_path}",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare {filesystem.name} filesystem "
                      f"and mounting {core.path} at {mountpoint}."):
        core.create_filesystem(fs_type=filesystem)
        core.mount(mount_point=mountpoint)
        sync()

    with TestRun.step(f"Create directory {nested_dir_path}."):
        Directory.create_directory(path=nested_dir_path, parents=True)
        sync()
        drop_caches(DropCachesMode.ALL)
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)

    with TestRun.step("Create test file."):
        classified_before = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        file_path = f"{test_dir_path}/test_file"
        (Dd().input("/dev/urandom").output(file_path).oflag("sync")
         .block_size(Size(1, Unit.MebiByte)).count(dd_blocks).run())
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)
        sync()
        drop_caches(DropCachesMode.ALL)
        test_file = File(file_path).refresh_item()

    with TestRun.step("Check classified occupancy."):
        classified_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        check_occupancy(classified_before + test_file.size, classified_after)

    with TestRun.step("Move test file out of classified directory."):
        classified_before = classified_after
        non_classified_before = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        test_file.move(destination=mountpoint)
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Check classified occupancy."):
        classified_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        check_occupancy(classified_before, classified_after)
        TestRun.LOGGER.info("Checking non-classified occupancy")
        non_classified_after = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        check_occupancy(non_classified_before, non_classified_after)

    with TestRun.step("Read test file."):
        classified_before = classified_after
        non_classified_before = non_classified_after
        (Dd().input(test_file.full_path).output("/dev/null")
         .iflag("sync").run())
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Check classified occupancy."):
        classified_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        check_occupancy(classified_before - test_file.size, classified_after)
        TestRun.LOGGER.info("Checking non-classified occupancy")
        non_classified_after = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        check_occupancy(non_classified_before + test_file.size, non_classified_after)

    with TestRun.step(f"Move test file to {nested_dir_path}."):
        classified_before = classified_after
        non_classified_before = non_classified_after
        test_file.move(destination=nested_dir_path)
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Check classified occupancy."):
        classified_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        check_occupancy(classified_before, classified_after)
        TestRun.LOGGER.info("Checking non-classified occupancy")
        non_classified_after = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        check_occupancy(non_classified_before, non_classified_after)

    with TestRun.step("Read test file."):
        classified_before = classified_after
        non_classified_before = non_classified_after
        (Dd().input(test_file.full_path).output("/dev/null")
         .block_size(Size(1, Unit.Blocks4096)).run())
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Check classified occupancy."):
        classified_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        check_occupancy(classified_before + test_file.size, classified_after)

    with TestRun.step("Check non-classified occupancy."):
        non_classified_after = cache.get_io_class_statistics(io_class_id=0).usage_stats.occupancy
        check_occupancy(non_classified_before - test_file.size, non_classified_after)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_directory_dir_operations(filesystem):
    """
        title: Test IO classification by directory operations.
        description: |
          Test if directory classification works properly after directory operations like move or
          rename.
        pass_criteria:
          - No kernel bug.
          - The operations themselves should not cause reclassification but IO after those
            operations should be reclassified to proper IO class.
          - Directory classification may work with a delay after loading IO class configuration or
            move/rename operations. Test checks if maximum delay is not exceeded.
    """

    non_classified_dir_path = f"{mountpoint}/non_classified"

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare(default_allocation="1.00")
        Udev.disable()

    with TestRun.step("Create and load IO class config file."):
        proper_ids = random.sample(range(1, ioclass_config.MAX_IO_CLASS_ID + 1), 2)
        ioclass_id_1 = proper_ids[0]
        classified_dir_path_1 = f"{mountpoint}/dir_{ioclass_id_1}"
        ioclass_id_2 = proper_ids[1]
        classified_dir_path_2 = f"{mountpoint}/dir_{ioclass_id_2}"
        # directory IO classes
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id_1,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{classified_dir_path_1}",
            ioclass_config_path=ioclass_config_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id_2,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{classified_dir_path_2}",
            ioclass_config_path=ioclass_config_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=32,
            eviction_priority=255,
            allocation="0.00",
            rule=f"metadata",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare {filesystem.name} filesystem "
                      f"and mount {core.path} at {mountpoint}."):
        core.create_filesystem(fs_type=filesystem)
        core.mount(mount_point=mountpoint)
        sync()

    with TestRun.step(f"Create a non-classified directory: {non_classified_dir_path}."):
        dir_1 = Directory.create_directory(path=non_classified_dir_path)

    with TestRun.step(f"Rename {non_classified_dir_path} to {classified_dir_path_1}."):
        dir_1.move(destination=classified_dir_path_1)

    with TestRun.step("Create files with delay check."):
        create_files_with_classification_delay_check(
            cache, directory=dir_1, ioclass_id=ioclass_id_1)

    with TestRun.step(f"Create {classified_dir_path_2}/subdir."):
        dir_2 = Directory.create_directory(path=f"{classified_dir_path_2}/subdir", parents=True)

    with TestRun.step("Create files with delay check."):
        create_files_with_classification_delay_check(cache, directory=dir_2,
                                                     ioclass_id=ioclass_id_2)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step(f"Move {dir_2.full_path} to {classified_dir_path_1}."):
        dir_2.move(destination=classified_dir_path_1)

    with TestRun.step("Read files with reclassification check."):
        read_files_with_reclassification_check(cache,
                                               target_ioclass_id=ioclass_id_1,
                                               source_ioclass_id=ioclass_id_2,
                                               directory=dir_2, with_delay=False)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step(f"Move {dir_2.full_path} to {mountpoint}."):
        dir_2.move(destination=mountpoint)

    with TestRun.step("Read files with reclassification check."):
        read_files_with_reclassification_check(cache,
                                               target_ioclass_id=0, source_ioclass_id=ioclass_id_1,
                                               directory=dir_2, with_delay=True)

    with TestRun.step(f"Remove {classified_dir_path_2}."):
        fs_utils.remove(path=classified_dir_path_2, force=True, recursive=True)
        sync()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step(f"Rename {classified_dir_path_1} to {classified_dir_path_2}."):
        dir_1.move(destination=classified_dir_path_2)

    with TestRun.step("Read files with reclassification check."):
        read_files_with_reclassification_check(cache,
                                               target_ioclass_id=ioclass_id_2,
                                               source_ioclass_id=ioclass_id_1,
                                               directory=dir_1, with_delay=True)

    with TestRun.step(f"Rename {classified_dir_path_2} to {non_classified_dir_path}."):
        dir_1.move(destination=non_classified_dir_path)

    with TestRun.step("Read files with reclassification check."):
        read_files_with_reclassification_check(cache,
                                               target_ioclass_id=0, source_ioclass_id=ioclass_id_2,
                                               directory=dir_1, with_delay=True)


def create_files_with_classification_delay_check(cache, directory: Directory, ioclass_id: int):
    start_time = datetime.now()
    occupancy_after = cache.get_io_class_statistics(
        io_class_id=ioclass_id).usage_stats.occupancy
    dd_blocks = 10
    dd_size = Size(dd_blocks, Unit.Blocks4096)
    file_counter = 0
    unclassified_files = []
    time_from_start = datetime.now() - start_time
    while time_from_start < ioclass_config.MAX_CLASSIFICATION_DELAY:
        occupancy_before = occupancy_after
        file_path = f"{directory.full_path}/test_file_{file_counter}"
        file_counter += 1
        time_from_start = datetime.now() - start_time
        (Dd().input("/dev/zero").output(file_path).oflag("sync")
         .block_size(Size(1, Unit.Blocks4096)).count(dd_blocks).run())
        occupancy_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).usage_stats.occupancy
        if occupancy_after - occupancy_before < dd_size:
            unclassified_files.append(file_path)

    if len(unclassified_files) == file_counter:
        TestRun.LOGGER.error("No files were properly classified within max delay time!")

    if len(unclassified_files):
        TestRun.LOGGER.info("Rewriting unclassified test files...")
        for file_path in unclassified_files:
            (Dd().input("/dev/zero").output(file_path).oflag("sync")
             .block_size(Size(1, Unit.Blocks4096)).count(dd_blocks).run())


def read_files_with_reclassification_check(cache, target_ioclass_id: int, source_ioclass_id: int,
                                           directory: Directory, with_delay: bool):
    start_time = datetime.now()
    target_occupancy_after = cache.get_io_class_statistics(
        io_class_id=target_ioclass_id).usage_stats.occupancy
    source_occupancy_after = cache.get_io_class_statistics(
        io_class_id=source_ioclass_id).usage_stats.occupancy
    files_to_reclassify = []
    target_ioclass_is_enabled = ioclass_is_enabled(cache, target_ioclass_id)

    for file in [item for item in directory.ls() if isinstance(item, File)]:
        target_occupancy_before = target_occupancy_after
        source_occupancy_before = source_occupancy_after
        time_from_start = datetime.now() - start_time
        dd = Dd().input(file.full_path).output("/dev/null").block_size(Size(1, Unit.Blocks4096))
        dd.run()
        target_occupancy_after = cache.get_io_class_statistics(
            io_class_id=target_ioclass_id).usage_stats.occupancy
        source_occupancy_after = cache.get_io_class_statistics(
            io_class_id=source_ioclass_id).usage_stats.occupancy

        if target_ioclass_is_enabled:
            if target_occupancy_after < target_occupancy_before:
                TestRun.LOGGER.error("Target IO class occupancy lowered!")
            elif target_occupancy_after - target_occupancy_before < file.size:
                files_to_reclassify.append(file)
                if with_delay and time_from_start <= ioclass_config.MAX_CLASSIFICATION_DELAY:
                    continue
                TestRun.LOGGER.error(
                    "Target IO class occupancy not changed properly!\n"
                    f"Expected: {(file.size + target_occupancy_before).set_unit(Unit.Blocks4096)}\n"
                    f"Actual: {target_occupancy_after}"
                )
        elif target_occupancy_after > target_occupancy_before and with_delay:
            files_to_reclassify.append(file)

        if source_occupancy_after >= source_occupancy_before:
            if file not in files_to_reclassify:
                files_to_reclassify.append(file)
            if with_delay and time_from_start <= ioclass_config.MAX_CLASSIFICATION_DELAY:
                continue
            TestRun.LOGGER.error(
                "Source IO class occupancy not changed properly!\n"
                f"Before: {source_occupancy_before}\n"
                f"After: {source_occupancy_after}"
            )

    if len(files_to_reclassify):
        TestRun.LOGGER.info("Rereading unclassified test files...")
        sync()
        drop_caches(DropCachesMode.ALL)
        for file in files_to_reclassify:
            (Dd().input(file.full_path).output("/dev/null")
             .block_size(Size(1, Unit.Blocks4096)).run())


def check_occupancy(expected: Size, actual: Size):
    if expected != actual:
        TestRun.LOGGER.error(f"Occupancy check failed!\nExpected: {expected}, actual: {actual}")


def ioclass_is_enabled(cache, ioclass_id: int):
    return [float(i.allocation) for i in cache.list_io_classes() if i.id == ioclass_id].pop() > 0.00
