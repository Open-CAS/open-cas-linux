#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import random
from itertools import permutations
from datetime import timedelta

import pytest

from api.cas.ioclass_config import IoClass
from api.cas.casadm_params import OutputFormat
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.filesystem.file import File
from test_utils.os_utils import drop_caches, DropCachesMode, sync, Udev
from .io_class_common import *


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_occupancy_directory():
    """
        title: Test for max occupancy set for ioclass based on directory
        description: |
          Create ioclass for 3 different directories, each with different
          max cache occupancy configured. Run IO against each directory and see
          if maximal occupancy set is repected.
        pass_criteria:
          - Max occupancy is set correctly for each ioclass
          - Each ioclass does not exceed max occupancy
    """
    cache, core = prepare()
    Udev.disable()

    filesystem = Filesystem.xfs

    cache_size_4k = int(cache.get_statistics().config_stats.cache_size.get_value(
                        Unit.Blocks4096))

    a_dir_id = 1
    a_dir_occ = '0.10'
    a_max_occ_4k = Size(int(cache_size_4k * float(a_dir_occ)),
                        Unit.Blocks4096)

    b_dir_id = 2
    b_dir_occ = '0.20'
    b_max_occ_4k = Size(int(cache_size_4k * float(b_dir_occ)),
                        Unit.Blocks4096)

    c_dir_id = 3
    c_dir_occ = '0.30'
    c_max_occ_4k = Size(int(cache_size_4k * float(c_dir_occ)),
                        Unit.Blocks4096)

    ioclass_config.remove_ioclass_config()
    ioclass_config.create_ioclass_config(False)

    TestRun.LOGGER.info(f"Preparing {filesystem.name} filesystem "
                        f"and mounting {core.system_path} at {mountpoint}")
    core.create_filesystem(filesystem)
    core.mount(mountpoint)
    sync()

    a_dir_path = f"{mountpoint}/A"
    TestRun.LOGGER.info(f"Creating first test directory: {a_dir_path}")
    fs_utils.create_directory(a_dir_path)

    b_dir_path = f"{mountpoint}/B"
    TestRun.LOGGER.info(f"Creating second test directory: {b_dir_path}")
    fs_utils.create_directory(b_dir_path)

    c_dir_path = f"{mountpoint}/C"
    TestRun.LOGGER.info(f"Creating third test directory: {c_dir_path}")
    fs_utils.create_directory(c_dir_path)

    with TestRun.step("Adding ioclasses for all dirs with 10, 20 and 30% max"
                      "occupancy respectively"):
        add_io_class(a_dir_id, 3, a_dir_occ, f"directory:{a_dir_path}&done")
        add_io_class(b_dir_id, 4, b_dir_occ, f"directory:{b_dir_path}&done")
        add_io_class(c_dir_id, 5, c_dir_occ, f"directory:{c_dir_path}&done")

        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Resetting cache stats"):
        cache.reset_counters()

    with TestRun.step(f"Performing IO for {a_dir_path} directory "
                      "with size bigger than max occupancy"):
        run_io_dir(core, a_dir_path, int(a_max_occ_4k.get_value(Unit.Blocks4096) * 2))

    with TestRun.step("Checking if ioclass {a_dir_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=a_dir_id).usage_stats.occupancy
        if occupancy > a_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {a_dir_id}."
                         f"Expected at most {a_max_occ_4k}, got: {occupancy}")

    with TestRun.step(f"Performing IO for {b_dir_path} directory "
                      "with size bigger than max occupancy"):
        run_io_dir(core, b_dir_path, int(b_max_occ_4k.get_value(Unit.Blocks4096) * 2))

    with TestRun.step("Checking if ioclass {b_dir_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=b_dir_id).usage_stats.occupancy
        if occupancy > b_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {b_dir_id}."
                         f"Expected at most {b_max_occ_4k}, got: {occupancy}")

    with TestRun.step(f"Performing IO for {c_dir_path} directory "
                      "with size bigger than max occupancy"):
        run_io_dir(core, c_dir_path, int(c_max_occ_4k.get_value(Unit.Blocks4096) * 2))

    with TestRun.step("Checking if ioclass {c_dir_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=c_dir_id).usage_stats.occupancy
        if occupancy > c_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {big_req_id}."
                         f"Expected at most {c_max_occ_4k}, got: {occupancy}")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_occupancy_req_size():
    """
        title: Test for max occupancy set for ioclass based on request size
        description: |
          Create ioclass for 3 different requests sizes, each with different
          max cache occupancy configured. Run IO with each request size and see
          if maximal occupancy set is repected.
        pass_criteria:
          - Max occupancy is set correctly for each ioclass
          - Each ioclass does not exceed max occupancy
    """
    cache, core = prepare()

    cache_size_4k = int(cache.get_statistics().config_stats.cache_size.get_value(
                        Unit.Blocks4096))
    small_req_id = 2
    small_req_size = Size(1, Unit.Blocks4096)
    small_req_occ = '0.10'
    small_req_rule = f"request_size:ge:0&request_size:le:"\
        f"{int(small_req_size)}&done"
    small_req_max_occ_4k = Size(int(cache_size_4k * float(small_req_occ)),
                                Unit.Blocks4096)

    med_req_id = 3
    med_req_size = Size(2, Unit.Blocks4096)
    med_req_occ = '0.20'
    med_req_rule = f"request_size:gt:{int(small_req_size)}&"\
                   f"request_size:le:{int(med_req_size)}&done"
    med_req_max_occ_4k = Size(int(cache_size_4k * float(med_req_occ)),
                              Unit.Blocks4096)

    big_req_id = 4
    big_req_occ = '0.30'
    big_req_size = 2 * med_req_size
    big_req_rule = f"request_size:gt:{int(med_req_size)}&done"
    big_req_max_occ_4k = Size(int(cache_size_4k * float(big_req_occ)),
                              Unit.Blocks4096)

    ioclass_config.remove_ioclass_config()
    ioclass_config.create_ioclass_config(False)

    with TestRun.step("Creating ioclasses for different reuqest size with "
                      "different max occupancy configured"):
        add_io_class(small_req_id, 3, small_req_occ, small_req_rule)
        add_io_class(big_req_id, 4, big_req_occ, big_req_rule)
        add_io_class(med_req_id, 5, med_req_occ, med_req_rule)

    with TestRun.step("Loading ioclass cofig"):
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Resetting cache stats"):
        cache.reset_counters()

    with TestRun.step(f"Performing small-req-class IO bigger than max occupancy"):
        run_fio_count(core, small_req_size, int((small_req_max_occ_4k * 2)
                                                / small_req_size))

    with TestRun.step("Checking if ioclass {small_req_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=small_req_id).usage_stats.occupancy
        if occupancy > small_req_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {small_req_id}."
                         f"Expected at most {small_req_max_occ_4k}, got: {occupancy}")

    with TestRun.step(f"Performing medium-req-class {med_req_id} IO bigger than max occupancy"):
        run_fio_count(core, med_req_size,
                      int((med_req_max_occ_4k * 2) / med_req_size))

    with TestRun.step("Checking if ioclass {med_req_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=med_req_id).usage_stats.occupancy
        if occupancy > med_req_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {med_req_id}."
                         f"Expected at most {med_req_max_occ_4k}, got: {occupancy}")

    with TestRun.step(f"Performing big-req-class {big_req_id} IO bigger than max occupancy"):
        run_fio_count(core, big_req_size,
                      int((big_req_max_occ_4k * 2) / big_req_size))

    with TestRun.step("Checking if ioclass {big_req_id} occupancy did not"
                      "exceed limit"):
        occupancy = cache.get_io_class_statistics(
            io_class_id=big_req_id).usage_stats.occupancy

        if occupancy > big_req_max_occ_4k:
            TestRun.fail(f"Wrong occupancy for ioclass id: {big_req_id}."
                         f"Expected at most {big_req_max_occ_4k}, got: {occupancy}")


def add_io_class(class_id, eviction_prio, occ, rule):
    ioclass_config.add_ioclass(
        ioclass_id=class_id,
        eviction_priority=eviction_prio,
        occupancy=occ,
        rule=rule,
        ioclass_config_path=ioclass_config_path,
    )


def run_io_dir(core, path, num_ios):
    dd = (
        Dd()
        .input("/dev/urandom")
        .output(f"{path}/tmp_file")
        .count(num_ios)
        .block_size(Size(1, Unit.Blocks4096))
    )
    dd.run()
    sync()
    drop_caches(DropCachesMode.ALL)


def run_fio_count(core, blocksize, num_ios):
    (Fio().create_command()
          .target(core)
          .io_engine(IoEngine.libaio)
          .read_write(ReadWrite.randread)
          .block_size(blocksize)
          .direct()
          .file_size(Size(10, Unit.GibiByte))
          .num_ios(num_ios)
          .run())
