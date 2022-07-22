#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from itertools import cycle

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


io_class_sizes = [4096, 16384, 65536, 262144, 1048576, 4194304,
                  16777216, 67108864, 268435456, 1073741824]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_stats_file_size_core():
    """
    title: Open CAS statistics values for file size - per core.
    description: Check Open CAS ability to assign correct IO class to file size.
    pass_criteria:
        - after FIO without direct statistics increases only for tested IO class
    """

    with TestRun.step("Prepare devices."):
        cache_devices, core_devices = prepare_devices()

    with TestRun.step("Start caches (one for each supported cache mode) and add core devices."):
        caches, cores = prepare_caches_and_cores(cache_devices, core_devices)

    with TestRun.step("Make filesystem on OpenCAS devices and mount it."):
        for core, fs in zip(cores, cycle(Filesystem)):
            mount_point = core.path.replace('/dev/', '/mnt/')
            core.create_filesystem(fs)
            core.mount(mount_point)
            sync()

    with TestRun.step("In default IO class configuration file set Eviction priority=1 "
                      "and load it for all caches."):
        io_classes = prepare_io_classes(caches, io_class_sizes)

    with TestRun.step("Run fio for all devices checking IO class statistics."):
        sizes = prepare_fio_sizes(io_class_sizes)
        size_min = Size(512, Unit.Byte)

        for io_class, size in zip(io_classes[2:-1], sizes):
            with TestRun.step(f"Testing IO class {io_class.id}."):
                with TestRun.step("Run fio for each device and check that "
                                  "only for tested IO class statistics increases."):
                    for core in cores:
                        core.reset_counters()
                        fio = fio_params(core, size_min, size)
                        result = fio.run()
                        sync()
                        drop_caches()
                        issued_reqs_no = \
                            result[0].write_requests_number() + result[0].read_requests_number()
                        served_reqs_no = \
                            core.get_io_class_statistics(io_class.id).request_stats.requests_total
                        check_statistics(caches[core.cache_id-1], io_class,
                                         issued_reqs_no, served_reqs_no)
                        fs_utils.remove(f"{core.mount_point}/*", force=True, recursive=True)
                    size_min = size + Size(1, Unit.Byte)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_stats_file_size_core_direct():
    """
    title: Open CAS statistics values for file size - per core.
    description: Check Open CAS ability to assign correct IO class to file size.
    pass_criteria:
        - after FIO with direct statistics increases for direct IO class
    """

    with TestRun.step("Prepare devices."):
        cache_devices, core_devices = prepare_devices()

    with TestRun.step("Start caches (one for each supported cache mode) and add core devices."):
        caches, cores = prepare_caches_and_cores(cache_devices, core_devices)

    with TestRun.step("In default IO class configuration file set Eviction priority=1 "
                      "and load it for all caches."):
        io_classes = prepare_io_classes(caches, io_class_sizes)

    with TestRun.step("Run fio for all devices checking IO class statistics."):
        sizes = prepare_fio_sizes(io_class_sizes)
        size_min = Size(512, Unit.Byte)

        io_class_direct = [io_class for io_class in io_classes if "direct" in io_class.rule][0]

        for io_class, size in zip(io_classes[2:-1], sizes):
            with TestRun.step(f"Testing IO class {io_class.id}."):
                with TestRun.step("Run fio for each device with direct=1 and check that "
                                  "for direct IO class statistics increases."):
                    for core in cores:
                        core.reset_counters()
                        fio = fio_params(core, size_min, size, direct=True)
                        result = fio.run()
                        sync()
                        drop_caches()
                        issued_reqs_no = \
                            result[0].write_requests_number() + result[0].read_requests_number()
                        served_reqs_no = core.get_io_class_statistics(io_class_direct.id).\
                            request_stats.requests_total
                        check_statistics(caches[core.cache_id-1], io_class_direct,
                                         issued_reqs_no, served_reqs_no)
                        fs_utils.remove(f"{core.path}/*", force=True, recursive=True)
                    size_min = size + Size(1, Unit.Byte)


def fio_params(core, size_min, size_max, direct=False):
    name_size_min = core.path if direct else f"{core.mount_point}/{round(size_min.get_value())}"
    name_size_max = core.path if direct else f"{core.mount_point}/{round(size_max.get_value())}"
    fio = Fio().create_command() \
        .io_engine(IoEngine.libaio) \
        .time_based() \
        .run_time(timedelta(seconds=64) if size_max <= Size(1, Unit.GibiByte)
                  else timedelta(seconds=200)) \
        .read_write(ReadWrite.randrw) \
        .io_depth(16) \
        .block_size(Size(1, Unit.Blocks512)) \
        .direct(direct)
    fio.add_job() \
        .file_size(size_min) \
        .target(name_size_min)
    fio.add_job() \
        .file_size(size_max) \
        .target(name_size_max)

    return fio


def check_statistics(cache, io_class, issued_reqs_no, served_reqs_no):
    TestRun.LOGGER.info(f"Checking IO class stats for cache {cache.cache_id}, "
                        f"cache mode {cache.get_cache_mode()}.")
    if served_reqs_no < issued_reqs_no:
        TestRun.LOGGER.error(f"Total requests too low for IO Class {io_class.id} "
                             f"{io_class.rule}: {served_reqs_no}, fio requests: {issued_reqs_no}")
    else:
        TestRun.LOGGER.info(f"Total requests for IO Class {io_class.id} "
                            f"{io_class.rule}: {served_reqs_no}, fio requests: {issued_reqs_no}")


def prepare_devices():
    cache_device = TestRun.disks['cache']
    cache_device.create_partitions([Size(10, Unit.GibiByte)] * 5)
    cache_devices = cache_device.partitions

    core_device = TestRun.disks['core']
    core_device.create_partitions([Size(5, Unit.GibiByte)] * 5)
    core_devices = core_device.partitions

    return cache_devices, core_devices


def prepare_caches_and_cores(cache_devices, core_devices):
    caches = [casadm.start_cache(dev, cache_mode=cache_mode, force=True)
              for dev, cache_mode in zip(cache_devices, CacheMode)]
    cores = [cache.add_core(dev) for dev, cache in zip(core_devices, caches)]
    for cache in caches:
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    return caches, cores


def prepare_io_classes(caches, sizes):
    ioclass_config.create_ioclass_config(add_default_rule=False)

    ioclass_config.add_ioclass(
        ioclass_id=0,
        eviction_priority=1,
        allocation="1.00",
        rule="unclassified",
    )
    ioclass_config.add_ioclass(
        ioclass_id=1,
        eviction_priority=1,
        allocation="1.00",
        rule="metadata&done",
    )
    for io_class_id, size in zip(range(11, 21), sizes):
        ioclass_config.add_ioclass(
            ioclass_id=io_class_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"file_size:le:{size}&done",
        )
    ioclass_config.add_ioclass(
        ioclass_id=21,
        eviction_priority=1,
        allocation="1.00",
        rule="file_size:gt:1073741824&done",
    )
    ioclass_config.add_ioclass(
        ioclass_id=22,
        eviction_priority=1,
        allocation="1.00",
        rule="direct&done",
    )
    [cache.load_io_class(ioclass_config.default_config_file_path) for cache in caches]
    io_classes = IoClass.csv_to_list(fs_utils.read_file(ioclass_config.default_config_file_path))

    return io_classes


def prepare_fio_sizes(sizes):
    sizes = [Size(size, Unit.Byte) for size in sizes]
    max_size = sizes[-1] + Size(100, Unit.MebiByte)
    sizes.append(max_size)

    return sizes
