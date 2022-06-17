#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import pytest
import time
from api.cas import casadm, ioclass_config
from api.cas.cache_config import CacheMode, CacheLineSize, CleaningPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools import fs_utils, disk_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils import os_utils
from test_utils.os_utils import Udev
from test_utils.size import Size, Unit
from test_utils.filesystem.file import File


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("filesystem", [Filesystem.ext4, Filesystem.xfs])
@pytest.mark.parametrizex("cleaning", [CleaningPolicy.alru, CleaningPolicy.nop])
def test_trim_eviction(cache_mode, cache_line_size, filesystem, cleaning):
    """
    title: Test verifying if trim requests do not cause eviction on CAS device.
    description: |
      When trim requests enabled and files are being added and removed from CAS device,
      there is no eviction (no reads from cache).
    pass_criteria:
      - Reads from cache device are the same before and after removing test file.
    """
    mount_point = "/mnt"
    test_file_path = os.path.join(mount_point, "test_file")

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks["core"]
        core_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

        cache_block_size = disk_utils.get_block_size(cache_disk)

    with TestRun.step("Start cache on device supporting trim and add core."):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
        cache.set_cleaning_policy(cleaning)
        Udev.disable()
        core = cache.add_core(core_dev)

    with TestRun.step("Create filesystem on CAS device and mount it."):
        core.create_filesystem(filesystem)
        core.mount(mount_point, ["discard"])

    with TestRun.step("Create ioclass config."):
        ioclass_config.create_ioclass_config()
        ioclass_config.add_ioclass(
            ioclass_id=1, eviction_priority=1, allocation="0.00", rule=f"metadata"
        )
        casadm.load_io_classes(
            cache_id=cache.cache_id, file=ioclass_config.default_config_file_path
        )

    with TestRun.step("Create random file using ddrescue."):
        test_file = create_file_with_ddrescue(core_dev, test_file_path)
        os_utils.sync()
        os_utils.drop_caches()
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)

    with TestRun.step("Remove file and create a new one."):
        cache_iostats_before = cache_dev.get_io_stats()
        data_reads_before = cache.get_io_class_statistics(io_class_id=0).block_stats.cache.reads
        metadata_reads_before = cache.get_io_class_statistics(
            io_class_id=1
        ).block_stats.cache.reads
        test_file.remove()
        os_utils.sync()
        os_utils.drop_caches()
        create_file_with_ddrescue(core_dev, test_file_path)
        os_utils.sync()
        os_utils.drop_caches()
        time.sleep(ioclass_config.MAX_CLASSIFICATION_DELAY.seconds)

    with TestRun.step("Check using iostat that reads from cache did not occur."):
        cache_iostats_after = cache_dev.get_io_stats()
        data_reads_after = cache.get_io_class_statistics(io_class_id=0).block_stats.cache.reads
        metadata_reads_after = cache.get_io_class_statistics(io_class_id=1).block_stats.cache.reads
        reads_before = cache_iostats_before.sectors_read
        reads_after = cache_iostats_after.sectors_read

        metadata_reads_diff = metadata_reads_after - metadata_reads_before
        data_reads_diff = data_reads_after - data_reads_before
        iostat_diff = (reads_after - reads_before) * cache_block_size

        if iostat_diff > int(metadata_reads_diff) or int(data_reads_diff) > 0:
            TestRun.fail(
                f"Number of reads from cache before and after removing test file "
                f"differs. Sectors read before: {reads_before}, sectors read after: {reads_after}."
                f"Data read from cache before {data_reads_before}, after {data_reads_after}."
                f"Metadata read from cache before {metadata_reads_before}, "
                f"after {metadata_reads_after}."
            )
        else:
            TestRun.LOGGER.info(
                "Number of reads from cache before and after removing test file is the same."
            )


def create_file_with_ddrescue(core_dev, test_file_path):
    dd = (
        Dd()
        .block_size(Size(1, Unit.MebiByte))
        .count(900)
        .input("/dev/urandom")
        .output(test_file_path)
        .oflag("sync")
    )
    dd.run()

    return File(test_file_path)
