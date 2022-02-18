#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import time
from itertools import permutations

import pytest

from api.cas import ioclass_config, casadm
from api.cas.ioclass_config import IoClass
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.filesystem.file import File
from test_utils.os_utils import sync, Udev
from test_utils.size import Size, Unit
from tests.io_class.io_class_common import prepare, ioclass_config_path, mountpoint


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_lba():
    """
        title: Test IO classification by lba.
        description: |
          Write data to random lba and check if it is cached according to range
          defined in ioclass rule
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on lba range defined in config.
    """

    ioclass_id = 1
    min_cached_lba = 56
    max_cached_lba = 200
    dd_size = Size(1, Unit.Blocks512)
    dd_count = 1

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Prepare and load IO class config."):
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"lba:ge:{min_cached_lba}&lba:le:{max_cached_lba}&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    with TestRun.step("Run IO and check if lbas from defined range are cached."):
        dirty_count = 0
        # '8' step is set to prevent writing cache line more than once
        TestRun.LOGGER.info(f"Writing to one sector in each cache line from range.")
        for lba in range(min_cached_lba, max_cached_lba, 8):
            dd = (
                Dd().input("/dev/zero")
                    .output(f"{core.path}")
                    .count(dd_count)
                    .block_size(dd_size)
                    .seek(lba)
                    .oflag("direct")
            )
            dd.run()
            dirty_count += 1

            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != dirty_count:
                TestRun.LOGGER.error(f"LBA {lba} not cached")

    with TestRun.step("Run IO and check if lba outside of defined range are not cached."):
        TestRun.LOGGER.info(f"Writing to sectors outside of cached range.")
        test_lba = [max_cached_lba + 1] + random.sample(
            [
                *range(0, min_cached_lba),
                *range(max_cached_lba + 1, int(core.size.get_value(Unit.Blocks512)))
            ],
            k=100)

        for lba in test_lba:
            prev_dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty

            dd = (
                Dd().input("/dev/zero")
                    .output(f"{core.path}")
                    .count(dd_count)
                    .block_size(dd_size)
                    .seek(lba)
                    .oflag("direct")
            )
            dd.run()

            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if prev_dirty != dirty:
                TestRun.LOGGER.error(f"Inappropriately cached lba: {lba}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_request_size():
    """
        title: Test IO classification by request size.
        description: Check if requests with size within defined range are cached.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly based on request size range defined in config.
    """

    ioclass_id = 1
    iterations = 100

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Create and load IO class config."):
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"request_size:ge:8192&request_size:le:16384&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Disable udev."):
        Udev.disable()

    with TestRun.step("Check if requests with size within defined range are cached."):
        cached_req_sizes = [Size(2, Unit.Blocks4096), Size(4, Unit.Blocks4096)]
        for i in range(iterations):
            cache.flush_cache()
            req_size = random.choice(cached_req_sizes)
            dd = (
                Dd().input("/dev/zero")
                    .output(core.path)
                    .count(1)
                    .block_size(req_size)
                    .oflag("direct")
            )
            dd.run()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != req_size.value / Unit.Blocks4096.value:
                TestRun.fail("Incorrect number of dirty blocks!")

    with TestRun.step("Flush cache."):
        cache.flush_cache()

    with TestRun.step("Check if requests with size outside of defined range are not cached"):
        not_cached_req_sizes = [
            Size(1, Unit.Blocks4096),
            Size(8, Unit.Blocks4096),
            Size(16, Unit.Blocks4096),
        ]
        for i in range(iterations):
            req_size = random.choice(not_cached_req_sizes)
            dd = (
                Dd().input("/dev/zero")
                    .output(core.path)
                    .count(1)
                    .block_size(req_size)
                    .oflag("direct")
            )
            dd.run()
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != 0:
                TestRun.fail("Dirty data present!")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", list(Filesystem) + [False])
def test_ioclass_direct(filesystem):
    """
        title: Direct IO classification.
        description: Check if direct requests are properly cached.
        pass_criteria:
          - No kernel bug.
          - Data from direct IO should be cached.
          - Data from buffered IO should not be cached and if performed to/from already cached data
            should cause reclassification to unclassified IO class.
    """

    ioclass_id = 1
    io_size = Size(random.randint(1000, 2000), Unit.Blocks4096)

    with TestRun.step("Prepare cache and core. Disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Create and load IO class config."):
        # direct IO class
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule="direct",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Prepare fio command."):
        fio = Fio().create_command() \
            .io_engine(IoEngine.libaio) \
            .size(io_size).offset(io_size) \
            .read_write(ReadWrite.write) \
            .target(f"{mountpoint}/tmp_file" if filesystem else core.path)

    with TestRun.step("Prepare filesystem."):
        if filesystem:
            TestRun.LOGGER.info(
                f"Preparing {filesystem.name} filesystem and mounting {core.path} at"
                f" {mountpoint}"
            )
            core.create_filesystem(filesystem)
            core.mount(mountpoint)
            sync()
        else:
            TestRun.LOGGER.info("Testing on raw exported object.")

    with TestRun.step(f"Run buffered writes to {'file' if filesystem else 'device'}"):
        base_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        fio.run()
        sync()

    with TestRun.step("Check if buffered writes are not cached."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        if new_occupancy != base_occupancy:
            TestRun.fail("Buffered writes were cached!\n"
                         f"Expected: {base_occupancy}, actual: {new_occupancy}")

    with TestRun.step(f"Run direct writes to {'file' if filesystem else 'device'}"):
        fio.direct()
        fio.run()
        sync()

    with TestRun.step("Check if direct writes are cached."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        if new_occupancy != base_occupancy + io_size:
            TestRun.fail("Wrong number of direct writes was cached!\n"
                         f"Expected: {base_occupancy + io_size}, actual: {new_occupancy}")

    with TestRun.step(f"Run buffered reads from {'file' if filesystem else 'device'}"):
        fio.remove_param("readwrite").remove_param("direct")
        fio.read_write(ReadWrite.read)
        fio.run()
        sync()

    with TestRun.step("Check if buffered reads caused reclassification."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        if new_occupancy != base_occupancy:
            TestRun.fail("Buffered reads did not cause reclassification!"
                         f"Expected occupancy: {base_occupancy}, actual: {new_occupancy}")

    with TestRun.step(f"Run direct reads from {'file' if filesystem else 'device'}"):
        fio.direct()
        fio.run()
        sync()

    with TestRun.step("Check if direct reads are cached."):
        new_occupancy = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.occupancy
        if new_occupancy != base_occupancy + io_size:
            TestRun.fail("Wrong number of direct reads was cached!\n"
                         f"Expected: {base_occupancy + io_size}, actual: {new_occupancy}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_metadata(filesystem):
    """
        title: Metadata IO classification.
        description: |
          Determine if every operation on files that cause metadata update results in increased
          writes to cached metadata.
        pass_criteria:
          - No kernel bug.
          - Metadata is classified properly.
    """
    # Exact values may not be tested as each file system has different metadata structure.
    test_dir_path = f"{mountpoint}/test_dir"

    with TestRun.step("Prepare cache and core. Disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Prepare and load IO class config file."):
        ioclass_id = random.randint(1, ioclass_config.MAX_IO_CLASS_ID)
        # metadata IO class
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule="metadata&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare {filesystem.name} filesystem and mount {core.path} "
                      f"at {mountpoint}."):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Create 20 test files."):
        requests_to_metadata_before = cache.get_io_class_statistics(
            io_class_id=ioclass_id).request_stats.write
        files = []
        for i in range(1, 21):
            file_path = f"{mountpoint}/test_file_{i}"
            dd = (
                Dd().input("/dev/urandom")
                    .output(file_path)
                    .count(random.randint(5, 50))
                    .block_size(Size(1, Unit.MebiByte))
                    .oflag("sync")
            )
            dd.run()
            files.append(File(file_path))

    with TestRun.step("Check requests to metadata."):
        requests_to_metadata_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).request_stats.write
        if requests_to_metadata_after == requests_to_metadata_before:
            TestRun.fail("No requests to metadata while creating files!")

    with TestRun.step("Rename all test files."):
        requests_to_metadata_before = requests_to_metadata_after
        for file in files:
            file.move(f"{file.full_path}_renamed")
        sync()

    with TestRun.step("Check requests to metadata."):
        requests_to_metadata_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).request_stats.write
        if requests_to_metadata_after == requests_to_metadata_before:
            TestRun.fail("No requests to metadata while renaming files!")

    with TestRun.step(f"Create directory {test_dir_path}."):
        requests_to_metadata_before = requests_to_metadata_after
        fs_utils.create_directory(path=test_dir_path)

        TestRun.LOGGER.info(f"Moving test files into {test_dir_path}")
        for file in files:
            file.move(test_dir_path)
        sync()

    with TestRun.step("Check requests to metadata."):
        requests_to_metadata_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).request_stats.write
        if requests_to_metadata_after == requests_to_metadata_before:
            TestRun.fail("No requests to metadata while moving files!")

    with TestRun.step(f"Remove {test_dir_path}."):
        fs_utils.remove(path=test_dir_path, force=True, recursive=True)

    with TestRun.step("Check requests to metadata."):
        requests_to_metadata_after = cache.get_io_class_statistics(
            io_class_id=ioclass_id).request_stats.write
        if requests_to_metadata_after == requests_to_metadata_before:
            TestRun.fail("No requests to metadata while deleting directory with files!")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_id_as_condition(filesystem):
    """
        title: IO class as a condition.
        description: |
          Load config in which IO class ids are used as conditions in other IO class definitions.
        pass_criteria:
          - No kernel bug.
          - IO is classified properly as described in IO class config.
    """

    base_dir_path = f"{mountpoint}/base_dir"
    ioclass_file_size = Size(random.randint(25, 50), Unit.MebiByte)
    ioclass_file_size_bytes = int(ioclass_file_size.get_value(Unit.Byte))

    with TestRun.step("Prepare cache and core. Disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Create and load IO class config file."):
        # directory condition
        ioclass_config.add_ioclass(
            ioclass_id=1,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{base_dir_path}",
            ioclass_config_path=ioclass_config_path,
        )
        # file size condition
        ioclass_config.add_ioclass(
            ioclass_id=2,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_size:eq:{ioclass_file_size_bytes}",
            ioclass_config_path=ioclass_config_path,
        )
        # direct condition
        ioclass_config.add_ioclass(
            ioclass_id=3,
            eviction_priority=1,
            allocation="1.00",
            rule="direct",
            ioclass_config_path=ioclass_config_path,
        )
        # IO class 1 OR 2 condition
        ioclass_config.add_ioclass(
            ioclass_id=4,
            eviction_priority=1,
            allocation="1.00",
            rule="io_class:1|io_class:2",
            ioclass_config_path=ioclass_config_path,
        )
        # IO class 4 AND file size condition (same as IO class 2)
        ioclass_config.add_ioclass(
            ioclass_id=5,
            eviction_priority=1,
            allocation="1.00",
            rule=f"io_class:4&file_size:eq:{ioclass_file_size_bytes}",
            ioclass_config_path=ioclass_config_path,
        )
        # IO class 3 condition
        ioclass_config.add_ioclass(
            ioclass_id=6,
            eviction_priority=1,
            allocation="1.00",
            rule="io_class:3",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)
        # CAS needs some time to resolve directory to inode
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)

    with TestRun.step(f"Prepare {filesystem.name} filesystem "
                      f"and mount {core.path} at {mountpoint}."):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        fs_utils.create_directory(base_dir_path)
        sync()
        # CAS needs some time to resolve directory to inode
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)

    with TestRun.step("Run IO fulfilling IO class 1 condition (and not IO class 2) and check if "
                      "it is classified properly."):
        # Should be classified as IO class 4
        base_occupancy = cache.get_io_class_statistics(io_class_id=4).usage_stats.occupancy
        non_ioclass_file_size = Size(random.randrange(1, 25), Unit.MebiByte)
        (Fio().create_command()
         .io_engine(IoEngine.libaio)
         .size(non_ioclass_file_size)
         .read_write(ReadWrite.write)
         .target(f"{base_dir_path}/test_file_1")
         .run())
        sync()
        new_occupancy = cache.get_io_class_statistics(io_class_id=4).usage_stats.occupancy

        if new_occupancy != base_occupancy + non_ioclass_file_size:
            TestRun.fail("Writes were not properly cached!\n"
                         f"Expected: {base_occupancy + non_ioclass_file_size}, "
                         f"actual: {new_occupancy}")

    with TestRun.step("Run IO fulfilling IO class 2 condition (and not IO class 1) and check if "
                      "it is classified properly."):
        # Should be classified as IO class 5
        base_occupancy = cache.get_io_class_statistics(io_class_id=5).usage_stats.occupancy
        (Fio().create_command()
         .io_engine(IoEngine.libaio)
         .size(ioclass_file_size)
         .read_write(ReadWrite.write)
         .target(f"{mountpoint}/test_file_2")
         .run())
        sync()
        new_occupancy = cache.get_io_class_statistics(io_class_id=5).usage_stats.occupancy

        if new_occupancy != base_occupancy + ioclass_file_size:
            TestRun.fail("Writes were not properly cached!\n"
                         f"Expected: {base_occupancy + ioclass_file_size}, actual: {new_occupancy}")

    with TestRun.step("Run IO fulfilling IO class 1 and 2 conditions and check if "
                      "it is classified properly."):
        # Should be classified as IO class 5
        base_occupancy = new_occupancy
        (Fio().create_command()
         .io_engine(IoEngine.libaio)
         .size(ioclass_file_size)
         .read_write(ReadWrite.write)
         .target(f"{base_dir_path}/test_file_3")
         .run())
        sync()
        new_occupancy = cache.get_io_class_statistics(io_class_id=5).usage_stats.occupancy

        if new_occupancy != base_occupancy + ioclass_file_size:
            TestRun.fail("Writes were not properly cached!\n"
                         f"Expected: {base_occupancy + ioclass_file_size}, actual: {new_occupancy}")

    with TestRun.step("Run direct IO fulfilling IO class 1 and 2 conditions and check if "
                      "it is classified properly."):
        # Should be classified as IO class 6
        base_occupancy = cache.get_io_class_statistics(io_class_id=6).usage_stats.occupancy
        (Fio().create_command()
         .io_engine(IoEngine.libaio)
         .size(ioclass_file_size)
         .read_write(ReadWrite.write)
         .target(f"{base_dir_path}/test_file_3")
         .direct()
         .run())
        sync()
        new_occupancy = cache.get_io_class_statistics(io_class_id=6).usage_stats.occupancy

        if new_occupancy != base_occupancy + ioclass_file_size:
            TestRun.fail("Writes were not properly cached!\n"
                         f"Expected: {base_occupancy + ioclass_file_size}, actual: {new_occupancy}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_conditions_or(filesystem):
    """
        title: IO class condition 'or'.
        description: |
          Load config with IO class combining 5 contradicting conditions connected by OR operator.
        pass_criteria:
          - No kernel bug.
          - Every IO fulfilling one condition is classified properly.
    """

    with TestRun.step("Prepare cache and core. Disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Create and load IO class config file."):
        # directories OR condition
        ioclass_config.add_ioclass(
            ioclass_id=1,
            eviction_priority=1,
            allocation="1.00",
            rule=f"directory:{mountpoint}/dir1|directory:{mountpoint}/dir2|directory:"
                 f"{mountpoint}/dir3|directory:{mountpoint}/dir4|directory:{mountpoint}/dir5",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step(f"Prepare {filesystem.name} filesystem "
                      f"and mount {core.path} at {mountpoint}."):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        for i in range(1, 6):
            fs_utils.create_directory(f"{mountpoint}/dir{i}")
        sync()

    with TestRun.step("Perform IO fulfilling each condition and check if occupancy raises."):
        for i in range(1, 6):
            file_size = Size(random.randint(25, 50), Unit.MebiByte)
            base_occupancy = cache.get_io_class_statistics(io_class_id=1).usage_stats.occupancy
            (Fio().create_command()
             .io_engine(IoEngine.libaio)
             .size(file_size)
             .read_write(ReadWrite.write)
             .target(f"{mountpoint}/dir{i}/test_file")
             .run())
            sync()
            new_occupancy = cache.get_io_class_statistics(io_class_id=1).usage_stats.occupancy

            if new_occupancy != base_occupancy + file_size:
                TestRun.fail("Occupancy has not increased correctly!\n"
                             f"Expected: {base_occupancy + file_size}, actual: {new_occupancy}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_conditions_and(filesystem):
    """
        title: IO class condition 'and'.
        description: |
          Load config with IO class combining 5 conditions contradicting
          at least one other condition.
        pass_criteria:
          - No kernel bug.
          - Every IO fulfilling one of the conditions is not classified.
    """

    file_size = Size(random.randint(25, 50), Unit.MebiByte)
    file_size_bytes = int(file_size.get_value(Unit.Byte))

    with TestRun.step("Prepare cache and core. Disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Create and load IO class config file."):
        # directories OR condition
        ioclass_config.add_ioclass(
            ioclass_id=1,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_size:gt:{file_size_bytes}&file_size:lt:{file_size_bytes}&"
                 f"file_size:ge:{file_size_bytes}&file_size:le:{file_size_bytes}&"
                 f"file_size:eq:{file_size_bytes}",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    TestRun.LOGGER.info(f"Preparing {filesystem.name} filesystem "
                        f"and mounting {core.path} at {mountpoint}")
    core.create_filesystem(filesystem)
    core.mount(mountpoint)
    sync()

    base_occupancy = cache.get_io_class_statistics(io_class_id=1).usage_stats.occupancy
    # Perform IO
    for size in [file_size, file_size + Size(1, Unit.MebiByte), file_size - Size(1, Unit.MebiByte)]:
        (Fio().create_command()
         .io_engine(IoEngine.libaio)
         .size(size)
         .read_write(ReadWrite.write)
         .target(f"{mountpoint}/test_file")
         .run())
        sync()
        new_occupancy = cache.get_io_class_statistics(io_class_id=1).usage_stats.occupancy

        if new_occupancy != base_occupancy:
            TestRun.fail("Unexpected occupancy increase!\n"
                         f"Expected: {base_occupancy}, actual: {new_occupancy}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_ioclass_effective_ioclass(filesystem):
    """
        title: Effective IO class with multiple non-exclusive conditions
        description: |
            Test CAS ability to properly classify IO fulfilling multiple conditions based on
            IO class ids and presence of '&done' annotation in IO class rules
        pass_criteria:
         - In every iteration first IO is classified to the last in order IO class
         - In every iteration second IO is classified to the IO class with '&done' annotation
    """
    with TestRun.LOGGER.step(f"Test prepare"):
        cache, core = prepare(default_allocation="1.00")
        Udev.disable()
        file_size = Size(10, Unit.Blocks4096)
        file_size_bytes = int(file_size.get_value(Unit.Byte))
        test_dir = f"{mountpoint}/test"
        rules = ["direct",  # rule contradicting other rules
                 f"directory:{test_dir}",
                 f"file_size:le:{2 * file_size_bytes}",
                 f"file_size:ge:{file_size_bytes // 2}"]

    with TestRun.LOGGER.step(f"Preparing {filesystem.name} filesystem "
                             f"and mounting {core.path} at {mountpoint}"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        fs_utils.create_directory(test_dir)
        sync()

    for i, permutation in TestRun.iteration(enumerate(permutations(range(1, 5)), start=1)):
        with TestRun.LOGGER.step("Load IO classes in order specified by permutation"):
            load_io_classes_in_permutation_order(rules, permutation, cache)
            io_class_id = 3 if rules[permutation.index(4)] == "direct" else 4

        with TestRun.LOGGER.step("Perform IO fulfilling the non-contradicting conditions"):
            base_occupancy = cache.get_io_class_statistics(
                io_class_id=io_class_id).usage_stats.occupancy
            fio = (Fio().create_command()
                   .io_engine(IoEngine.libaio)
                   .size(file_size)
                   .read_write(ReadWrite.write)
                   .target(f"{test_dir}/test_file{i}"))
            fio.run()
            sync()

        with TestRun.LOGGER.step("Check if IO was properly classified "
                                 "(to the last non-contradicting IO class)"):
            new_occupancy = cache.get_io_class_statistics(
                io_class_id=io_class_id).usage_stats.occupancy
            if new_occupancy != base_occupancy + file_size:
                TestRun.LOGGER.error("Wrong IO classification!\n"
                                     f"Expected: {base_occupancy + file_size}, "
                                     f"actual: {new_occupancy}")

        with TestRun.LOGGER.step("Add '&done' to the second in order non-contradicting condition"):
            io_class_id = add_done_to_second_non_exclusive_condition(rules, permutation, cache)

        with TestRun.LOGGER.step("Repeat IO"):
            base_occupancy = cache.get_io_class_statistics(
                io_class_id=io_class_id).usage_stats.occupancy
            fio.run()
            sync()

        with TestRun.LOGGER.step("Check if IO was properly classified "
                                 "(to the IO class with '&done' annotation)"):
            new_occupancy = cache.get_io_class_statistics(
                io_class_id=io_class_id).usage_stats.occupancy
            if new_occupancy != base_occupancy + file_size:
                TestRun.LOGGER.error("Wrong IO classification!\n"
                                     f"Expected: {base_occupancy + file_size}, "
                                     f"actual: {new_occupancy}")


def load_io_classes_in_permutation_order(rules, permutation, cache):
    ioclass_config.remove_ioclass_config(ioclass_config_path=ioclass_config_path)
    ioclass_config.create_ioclass_config(
        add_default_rule=False, ioclass_config_path=ioclass_config_path
    )
    # To make test more precise all workload except of tested ioclass should be
    # put in pass-through mode
    ioclass_list = [IoClass.default(allocation="0.0")]
    for n in range(len(rules)):
        ioclass_list.append(IoClass(class_id=permutation[n], rule=rules[n]))
    IoClass.save_list_to_config_file(ioclass_list,
                                     add_default_rule=False,
                                     ioclass_config_path=ioclass_config_path)
    casadm.load_io_classes(cache.cache_id, file=ioclass_config_path)


def add_done_to_second_non_exclusive_condition(rules, permutation, cache):
    non_exclusive_conditions = 0
    second_class_id = 1
    while True:
        idx = permutation.index(second_class_id)
        if rules[idx] != "direct":
            non_exclusive_conditions += 1
        if non_exclusive_conditions == 2:
            break
        second_class_id += 1
    fs_utils.replace_first_pattern_occurrence(ioclass_config_path,
                                              rules[idx], f"{rules[idx]}&done")
    sync()
    casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)
    return second_class_id
