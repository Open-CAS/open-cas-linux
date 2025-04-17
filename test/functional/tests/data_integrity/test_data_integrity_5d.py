#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import datetime
import itertools
import re
import pytest

from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.ioclass_config import IoClass
from core.test_run import TestRun
from test_tools.fs_tools import Filesystem, create_directory, check_if_directory_exists, \
    read_file, crc32sum
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.os_tools import sync
from type_def.size import Unit, Size

template_config_path = "/etc/opencas/ioclass-config.csv"


def shuffled_fs_list(n):
    return random.sample(list(itertools.islice(itertools.cycle(Filesystem), n)), n)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core3", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core4", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("filesystems", [shuffled_fs_list(4)])
def test_data_integrity_5d_with_io_classification(filesystems):
    """
    title: Data integrity long test with I/O classification.
    description: |
        Test running workload with data verification and I/O classification by file size
        on multiple cache instances with different cache modes and filesystems.
    pass_criteria:
      - System does not crash.
      - All operations complete successfully.
      - Data consistency is being preserved.
    """
    cache_modes = [CacheMode.WT, CacheMode.WB, CacheMode.WA, CacheMode.WO]
    runtime = datetime.timedelta(days=5)

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_devices = [TestRun.disks['core1'],
                        TestRun.disks['core2'],
                        TestRun.disks['core3'],
                        TestRun.disks['core4']]

        cache_device.create_partitions([Size(50, Unit.GibiByte)] * len(core_devices))

        core_partitions = []
        core_size = Size(150, Unit.GibiByte)
        for core_dev in core_devices:
            core_dev.create_partitions([core_size])
            core_partitions.append(core_dev.partitions[0])
        sync()

    with TestRun.step("Start caches, each in other cache mode"):
        caches = [
            casadm.start_cache(cache_dev=cache_part, cache_mode=cache_mode, force=True)
            for cache_part, cache_mode in zip(cache_device.partitions, cache_modes)
        ]

    with TestRun.step("Add one core to each cache"):
        cores = [
            cache.add_core(core_dev=core_part)
            for cache, core_part in zip(caches, core_partitions)
        ]

    with TestRun.step("Load default I/O class config for each cache"):
        for cache in caches:
            cache.load_io_class(template_config_path)

    with TestRun.step("Create filesystems on exported objects"):
        for filesystem, core in zip(filesystems, cores):
            core.create_filesystem(fs_type=filesystem)

    with TestRun.step("Mount cached volumes"):
        for core in cores:
            mount_point = core.path.replace('/dev/', '/mnt/')
            if not check_if_directory_exists(mount_point):
                create_directory(mount_point)
            core.mount(mount_point)
            sync()

    with TestRun.step("Prepare fio workload config"):
        template_io_classes = IoClass.csv_to_list(read_file(template_config_path))
        config_max_file_sizes = [
            int(re.search(r'\d+', io_class.rule).group())
            for io_class in template_io_classes if io_class.rule.startswith("file_size:le")
        ]
        config_max_file_sizes.append(config_max_file_sizes[-1] * 2)
        io_class_section_size = Size(
            int(core_size.get_value(Unit.GibiByte) / len(config_max_file_sizes)),
            Unit.GibiByte
        )

        fio = Fio()
        fio_run = fio.create_command()
        fio.base_cmd_parameters.set_param(
            'alloc-size', int(Size(1, Unit.GiB).get_value(Unit.KiB))
        )

        fio_run.io_engine(IoEngine.libaio)
        fio_run.direct()
        fio_run.time_based()
        fio_run.do_verify()
        fio_run.verify(VerifyMethod.md5)
        fio_run.verify_dump()
        fio_run.run_time(runtime)
        fio_run.read_write(ReadWrite.randrw)
        fio_run.io_depth(128)
        fio_run.blocksize_range(
            [(Size(512, Unit.Byte).get_value(), Size(128, Unit.KibiByte).get_value())]
        )

        for core in cores:
            min_file_size = 512
            for max_file_size in config_max_file_sizes:
                # 10000 limit of files for reasonable time of preparation ~2hours
                nr_files = min(10000, int(io_class_section_size * 0.9 / max_file_size))

                fio_job = fio_run.add_job()
                fio_job.directory(core.mount_point)
                fio_job.nr_files(nr_files)
                fio_job.file_size_range([(min_file_size, max_file_size)])
                min_file_size = max_file_size

    with TestRun.step("Run test workload on filesystems with verification"):
        fio_run.run(fio_timeout=runtime + datetime.timedelta(hours=3))

    with TestRun.step("Unmount cores"):
        for core in cores:
            core.unmount()

    with TestRun.step("Calculate crc32 for each core"):
        core_crc32s = [crc32sum(core.path, timeout=timedelta(hours=4)) for core in cores]

    with TestRun.step("Stop caches"):
        for cache in caches:
            cache.stop()

    with TestRun.step("Calculate crc32 for each core"):
        dev_crc32s = [crc32sum(dev.path, timeout=timedelta(hours=4)) for dev in core_devices]

    with TestRun.step("Compare crc32 sums for cores and core devices"):
        for core_crc32, dev_crc32, mode, fs in zip(
                core_crc32s, dev_crc32s, cache_modes, filesystems
        ):
            if core_crc32 != dev_crc32:
                TestRun.fail("Crc32 sums of core and core device do not match! "
                             f"Cache mode: {mode} Filesystem: {fs}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core3", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core4", DiskTypeLowerThan("cache"))
def test_data_integrity_5d():
    """
    title: Data integrity long test on raw devices.
    description: |
        Test running workload with data verification on multiple cache instances with
        different cache modes.
    pass_criteria:
      - System does not crash.
      - All operations complete successfully.
      - Data consistency is preserved.
    """
    cache_modes = [CacheMode.WT, CacheMode.WB, CacheMode.WA, CacheMode.WO]
    runtime = datetime.timedelta(days=5)

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks['cache']
        core_devices = [TestRun.disks['core1'],
                        TestRun.disks['core2'],
                        TestRun.disks['core3'],
                        TestRun.disks['core4']]

        cache_device.create_partitions([Size(50, Unit.GibiByte)] * len(core_devices))

        core_partitions = []
        for core_dev in core_devices:
            core_dev.create_partitions([Size(150, Unit.GibiByte)])
            core_partitions.append(core_dev.partitions[0])
        sync()

    with TestRun.step("Start caches, each in different cache mode"):
        caches = [
            casadm.start_cache(cache_device, cache_mode, force=True)
            for cache_device, cache_mode in zip(cache_device.partitions, cache_modes)
        ]

    with TestRun.step("Add one core to each cache"):
        cores = [
            casadm.add_core(cache, core_dev=core_device)
            for cache, core_device in zip(caches, core_devices)
        ]

    with TestRun.step("Prepare fio workload config"):
        fio_run = Fio().create_command()
        fio_run.io_engine(IoEngine.libaio)
        fio_run.direct()
        fio_run.time_based()
        fio_run.do_verify()
        fio_run.verify(VerifyMethod.md5)
        fio_run.verify_dump()
        fio_run.run_time(runtime)
        fio_run.read_write(ReadWrite.randrw)
        fio_run.io_depth(128)
        fio_run.blocksize_range(
            [(Size(512, Unit.Byte).get_value(), Size(128, Unit.KibiByte).get_value())]
        )
        for core in cores:
            fio_job = fio_run.add_job()
            fio_job.target(core)

    with TestRun.step("Run test workload with data verification"):
        fio_run.run(fio_timeout=runtime + datetime.timedelta(hours=2))

    with TestRun.step("Calculate crc32 for each core"):
        core_crc32s = [crc32sum(core.path, timeout=timedelta(hours=4)) for core in cores]

    with TestRun.step("Stop caches"):
        for cache in caches:
            cache.stop()

    with TestRun.step("Calculate crc32 for each core"):
        dev_crc32s = [crc32sum(dev.path, timeout=timedelta(hours=4)) for dev in core_devices]

    with TestRun.step("Compare crc32 sums for cores and core devices"):
        for core_crc32, dev_crc32, mode in zip(core_crc32s, dev_crc32s, cache_modes):
            if core_crc32 != dev_crc32:
                TestRun.fail("Crc32 sums of core and core device do not match! "
                             f"Cache mode: {mode}")
