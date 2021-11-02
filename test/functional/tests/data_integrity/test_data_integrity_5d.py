#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import datetime
import itertools

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.filesystem.file import File
from test_utils.os_utils import sync
from test_utils.size import Unit, Size


start_size = Size(512, Unit.Byte).get_value()
stop_size = Size(128, Unit.KibiByte).get_value()
file_min_size = Size(4, Unit.KibiByte).get_value()
file_max_size = Size(2, Unit.GibiByte).get_value()
runtime = datetime.timedelta(days=5)


def shuffled_fs_list(n):
    return random.sample(list(itertools.islice(itertools.cycle(Filesystem), n)), n)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core3", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core4", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("filesystems", [shuffled_fs_list(4)])
def test_data_integrity_5d_dss(filesystems):
    """
        title: |
          Data integrity test on three cas instances with different
          file systems with duration time equal to 5 days
        description: |
          Create 3 cache instances on caches equal to 50GB and cores equal to 150GB
          with different file systems, and run workload with data verification.
        pass_criteria:
            - System does not crash.
            - All operations complete successfully.
            - Data consistency is being preserved.
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_devices, core_devices = prepare_devices()

    with TestRun.step("Run 4 cache instances in different cache modes, add single core to each"):
        cache_modes = [CacheMode.WT, CacheMode.WB, CacheMode.WA, CacheMode.WO]
        caches = []
        cores = []
        for i in range(4):
            cache, core = start_instance(cache_devices[i], core_devices[i], cache_modes[i])
            caches.append(cache)
            cores.append(core)

    with TestRun.step("Load default io class config for each cache"):
        for cache in caches:
            cache.load_io_class("/etc/opencas/ioclass-config.csv")

    with TestRun.step("Create filesystems and mount cores"):
        for i, core in enumerate(cores):
            mount_point = core.path.replace('/dev/', '/mnt/')
            if not fs_utils.check_if_directory_exists(mount_point):
                fs_utils.create_directory(mount_point)
            TestRun.LOGGER.info(f"Create filesystem {filesystems[i].name} on {core.path}")
            core.create_filesystem(filesystems[i])
            TestRun.LOGGER.info(f"Mount filesystem {filesystems[i].name} on {core.path} to "
                                f"{mount_point}")
            core.mount(mount_point)
            sync()

    with TestRun.step("Run test workloads on filesystems with verification"):
        fio_run = Fio().create_command()
        fio_run.io_engine(IoEngine.libaio)
        fio_run.direct()
        fio_run.time_based()
        fio_run.nr_files(4096)
        fio_run.file_size_range([(file_min_size, file_max_size)])
        fio_run.do_verify()
        fio_run.verify(VerifyMethod.md5)
        fio_run.verify_dump()
        fio_run.run_time(runtime)
        fio_run.read_write(ReadWrite.randrw)
        fio_run.io_depth(128)
        fio_run.blocksize_range([(start_size, stop_size)])
        for core in cores:
            fio_job = fio_run.add_job()
            fio_job.directory(core.mount_point)
            fio_job.size(core.size)
        fio_run.run()

    with TestRun.step("Unmount cores"):
        for core in cores:
            core.unmount()

    with TestRun.step("Calculate md5 for each core"):
        core_md5s = [File(core.full_path).md5sum() for core in cores]

    with TestRun.step("Stop caches"):
        for cache in caches:
            cache.stop()

    with TestRun.step("Calculate md5 for each core"):
        dev_md5s = [File(dev.full_path).md5sum() for dev in core_devices]

    with TestRun.step("Compare md5 sums for cores and core devices"):
        for core_md5, dev_md5, mode, fs in zip(core_md5s, dev_md5s, cache_modes, filesystems):
            if core_md5 != dev_md5:
                TestRun.fail(f"MD5 sums of core and core device do not match! "
                             f"Cache mode: {mode} Filesystem: {fs}")


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core3", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core4", DiskTypeLowerThan("cache"))
def test_data_integrity_5d():
    """
        title: |
          Data integrity test on three cas instances with different
          cache modes with duration time equal to 5 days
        description: |
          Create 3 cache instances with different cache modes on caches equal to 50GB
          and cores equal to 150GB, and run workload with data verification.
        pass_criteria:
            - System does not crash.
            - All operations complete successfully.
            - Data consistency is preserved.
    """
    with TestRun.step("Prepare cache and core devices"):
        cache_devices, core_devices = prepare_devices()

    with TestRun.step("Run 4 cache instances in different cache modes, add single core to each"):
        cache_modes = [CacheMode.WT, CacheMode.WB, CacheMode.WA, CacheMode.WO]
        caches = []
        cores = []
        for i in range(4):
            cache, core = start_instance(cache_devices[i], core_devices[i], cache_modes[i])
            caches.append(cache)
            cores.append(core)

    with TestRun.step("Run test workloads with verification"):
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
        fio_run.blocksize_range([(start_size, stop_size)])
        for core in cores:
            fio_job = fio_run.add_job()
            fio_job.target(core)
        fio_run.run()

    with TestRun.step("Calculate md5 for each core"):
        core_md5s = [File(core.full_path).md5sum() for core in cores]

    with TestRun.step("Stop caches"):
        for cache in caches:
            cache.stop()

    with TestRun.step("Calculate md5 for each core"):
        dev_md5s = [File(dev.full_path).md5sum() for dev in core_devices]

    with TestRun.step("Compare md5 sums for cores and core devices"):
        for core_md5, dev_md5, mode in zip(core_md5s, dev_md5s, cache_modes):
            if core_md5 != dev_md5:
                TestRun.fail(f"MD5 sums of core and core device do not match! "
                             f"Cache mode: {mode}")


def start_instance(cache_device, core_device, cache_mode):
    TestRun.LOGGER.info(f"Starting cache with cache mode {cache_mode}")
    cache = casadm.start_cache(cache_device, cache_mode, force=True)
    TestRun.LOGGER.info(f"Adding core device to cache device")
    core = casadm.add_core(cache, core_dev=core_device)

    return cache, core


def prepare_devices():
    cache_device = TestRun.disks['cache']
    core_devices = [TestRun.disks['core1'],
                    TestRun.disks['core2'],
                    TestRun.disks['core3'],
                    TestRun.disks['core4']]

    cache_device.create_partitions([Size(50, Unit.GibiByte),
                                    Size(50, Unit.GibiByte),
                                    Size(50, Unit.GibiByte),
                                    Size(50, Unit.GibiByte)])

    core_partitions = []
    for core_dev in core_devices:
        core_dev.create_partitions([Size(150, Unit.GibiByte)])
        core_partitions.append(core_dev.partitions[0])
    sync()

    return cache_device.partitions, core_partitions
