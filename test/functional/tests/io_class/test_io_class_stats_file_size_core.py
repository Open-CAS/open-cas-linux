#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import re
import pytest

from datetime import timedelta
from api.cas import casadm, ioclass_config
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.ioclass_config import IoClass
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import sync, drop_caches
from test_utils.size import Size, Unit
from tests.io_class.io_class_common import template_config_path


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_stats_file_size_core_fs(cache_mode: CacheMode, filesystem: Filesystem):
    """
    title: Open CAS statistics values per core for IO classification by file size.
    description: |
      Check Open CAS ability to assign correct IO class based on the file size.
      Test checking configuration with different filesystems on each core.
    pass_criteria:
        - after FIO with direct statistics increase only for direct IO class
    """

    with TestRun.step("Prepare devices"):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        cache_device = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(5, Unit.GibiByte)])
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache and add core device"):
        cache = casadm.start_cache(cache_device, cache_mode, force=True)
        core = cache.add_core(core_device)

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Make filesystem on OpenCAS device and mount it"):
        mount_point = core.path.replace('/dev/', '/mnt/')
        core.create_filesystem(filesystem)
        core.mount(mount_point)

    with TestRun.step("In default IO class configuration file set eviction priority=1 "
                      "and load it"):
        io_classes = prepare_io_classes(cache)
        *file_size_based_io_classes, _ = io_classes

    with TestRun.step("Prepare file sizes for fio setup"):
        sizes = prepare_fio_sizes(file_size_based_io_classes)
        size_min = Size(512, Unit.Byte)

    for io_class, size in TestRun.iteration(
            zip(file_size_based_io_classes, sizes),
            "Run fio and check IO class statistics"
    ):
        with TestRun.step(f"Run fio with IO class {io_class.id} file sizes"):
            TestRun.LOGGER.info(f"Testing {core.filesystem.name} filesystem.")
            core.reset_counters()
            fio = fio_params(core, size_min, size)
            result = fio.run(fio_timeout=timedelta(minutes=5))
            sync()
            drop_caches()

        with TestRun.step(f"Check that statistics increase only for IO class {io_class.id}"):
            issued_reqs_no = \
                result[0].write_requests_number() + result[0].read_requests_number()
            check_statistics(cache, core, io_classes, io_class, issued_reqs_no)
            fs_utils.remove(f"{core.mount_point}/*", force=True, recursive=True)

            size_min = size + Size(512, Unit.Byte)


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_stats_file_size_core_direct(cache_mode: CacheMode):
    """
    title: Open CAS statistics values per core for IO classification by file size - direct IO.
    description: Check Open CAS ability to assign correct IO class when IO is issued in direct mode.
    pass_criteria:
        - after FIO with direct statistics increase only for direct IO class
    """

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(10, Unit.GibiByte)])
        cache_device = cache_device.partitions[0]

        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(5, Unit.GibiByte)])
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache and add core devices"):
        cache = casadm.start_cache(cache_device, cache_mode=cache_mode, force=True)
        core = cache.add_core(core_device)

    with TestRun.step("Disable cleaning and sequential cutoff"):
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("In default IO class configuration file set Eviction priority=1 "
                      "and load it for all caches"):
        io_classes = prepare_io_classes(cache)
        *file_size_based_io_classes, io_class_direct = io_classes

    with TestRun.step("Prepare file sizes for fio setup"):
        sizes = prepare_fio_sizes(file_size_based_io_classes)
        size_min = Size(512, Unit.Byte)

    for io_class, size in TestRun.iteration(
            zip(file_size_based_io_classes, sizes),
            "Run fio and check IO class statistics"
    ):
        with TestRun.step(f"Run fio with IO class {io_class.id} file sizes and with direct=1"):
            core.reset_counters()
            fio = fio_params(core, size_min, size, direct=True)
            result = fio.run(fio_timeout=timedelta(minutes=5))
            sync()
            drop_caches()

        with TestRun.step(f"Check that statistics increase only for direct IO class"):
            issued_reqs_no = \
                result[0].write_requests_number() + result[0].read_requests_number()
            check_statistics(cache, core, io_classes, io_class_direct, issued_reqs_no)
            fs_utils.remove(f"{core.path}/*", force=True, recursive=True)

            size_min = size + Size(512, Unit.Byte)


def fio_params(core, size_min, size_max, direct=False):
    name_size_min = core.path if direct else f"{core.mount_point}/{round(size_min.get_value())}"
    name_size_max = core.path if direct else f"{core.mount_point}/{round(size_max.get_value())}"
    fio = Fio().create_command() \
        .io_engine(IoEngine.libaio) \
        .read_write(ReadWrite.randwrite) \
        .io_depth(16) \
        .block_size(Size(1, Unit.Blocks512)) \
        .direct(direct)
    fio.add_job() \
        .file_size(size_min) \
        .io_size(size_min * 1.1) \
        .target(name_size_min)
    fio.add_job() \
        .file_size(size_max) \
        .io_size(size_max * 1.1) \
        .target(name_size_max)

    return fio


def check_statistics(cache, core, io_classes, tested_io_class, issued_reqs_no):
    TestRun.LOGGER.info(f"Checking IO class stats for cache {cache.cache_id}, "
                        f"cache mode {cache.get_cache_mode()}.")

    untouched_io_classes = io_classes.copy()
    untouched_io_classes.remove(tested_io_class)

    served_reqs_no = core.get_io_class_statistics(tested_io_class.id).request_stats.requests_total
    if served_reqs_no <= 0:
        TestRun.LOGGER.error(f"Total requests too low for IO Class {tested_io_class.id} "
                             f"{tested_io_class.rule}: {served_reqs_no}, "
                             f"fio requests: {issued_reqs_no}.")
    else:
        TestRun.LOGGER.info(f"Total requests for IO Class {tested_io_class.id} "
                            f"{tested_io_class.rule}: {served_reqs_no}, "
                            f"fio requests: {issued_reqs_no}.")

    for io_class in untouched_io_classes:
        served_reqs_no = core.get_io_class_statistics(io_class.id).request_stats.requests_total
        if served_reqs_no > 0:
            TestRun.LOGGER.error(f"Total requests too high for IO Class {io_class.id} "
                                 f"{io_class.rule}: {served_reqs_no}, should be 0.")


def prepare_io_classes(cache):
    template_io_classes = IoClass.csv_to_list(fs_utils.read_file(template_config_path))
    test_io_classes = []

    for io_class in template_io_classes:
        if "metadata" in io_class.rule:
            continue
        else:
            test_io_class = io_class
            test_io_class.priority = 1
            test_io_class.allocation = "1.00"
            test_io_classes.append(test_io_class)

    IoClass.save_list_to_config_file(
        test_io_classes,
        add_default_rule=False,
        ioclass_config_path=ioclass_config.default_config_file_path
    )

    cache.load_io_class(ioclass_config.default_config_file_path)

    return test_io_classes[1:]


def prepare_fio_sizes(file_size_based_io_classes):
    sizes = [*dict.fromkeys(
        [int(re.search(r"\d+", s.rule).group()) for s in file_size_based_io_classes]
    )]  # removing duplicated size values without changing the values order
    sizes = [Size(size, Unit.Byte) for size in sizes]
    max_size = sizes[-1] + Size(100, Unit.MebiByte)
    sizes.append(max_size)

    return sizes
