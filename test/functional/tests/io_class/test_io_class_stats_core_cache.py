#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re
from itertools import cycle

import pytest

from api.cas import casadm, ioclass_config
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.casadm_params import StatsFilter
from api.cas.ioclass_config import IoClass
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.os_utils import sync, drop_caches, Udev
from test_utils.size import Size, Unit


num_of_cores = 3


@pytest.mark.parametrize("per_core", [False, True])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_stats_core_cache(per_core):
    """
    title: Open CAS statistics values for IO classes - per core/cache.
    description: Check Open CAS ability to display correct value in statistics
                 for all supported IO classes for given core/cache device.
    pass_criteria:
        - proper statistics after fio
        - statistics doesn't change after stop and load cache
    """

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(20, Unit.GibiByte)])
        cache_device = cache_device.partitions[0]

        core_device = TestRun.disks['core']
        core_device.create_partitions([Size(10, Unit.GibiByte)] * num_of_cores)
        core_devices = core_device.partitions

    with TestRun.step("Start cache in Write-Through mode and add core devices."):
        cache = casadm.start_cache(cache_device, cache_mode=CacheMode.WT, force=True)
        cores = [cache.add_core(dev) for dev in core_devices]

        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.purge_cache()
        cache.reset_counters()

        Udev.disable()

    with TestRun.step(f"Validate IO class usage statistics after start "
                      f"for {'each core' if per_core else 'cache'}."):
        devices = cores if per_core else [cache]
        for dev in devices:
            stats = dev.get_statistics_flat(0, [StatsFilter.usage])
            TestRun.LOGGER.info(f"Check stats "
                                f"for {f'core {dev.core_id}' if per_core else 'cache'}.")
            for name, value in stats.items():
                check_value(name, value.get_value(), 0)

    with TestRun.step("Load IO class configuration file for cache."):
        io_classes = IoClass.csv_to_list(
            fs_utils.read_file("/etc/opencas/ioclass-config.csv"))
        for io_class in io_classes:
            if 'metadata' in io_class.rule:
                io_class.allocation = 0
        IoClass.save_list_to_config_file(io_classes, add_default_rule=False)
        cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Make filesystem on OpenCAS devices and mount it."):
        for core, fs in zip(cores, Filesystem):
            mount_point = core.path.replace('/dev/', '/mnt/')
            core.create_filesystem(fs)
            core.mount(mount_point)
            sync()
            drop_caches()

    with TestRun.step("Run fio for each device and validate IO class usage, "
                      "request and block level statistics values."):
        saved_stats = []
        tested_io_classes = io_classes[2:]
        sizes = get_sizes(tested_io_classes)
        cache_size = cache.size.get_value(Unit.Blocks4096)

        s = '' if per_core else '(s)'
        stats_size = ['occupancy', 'clean', 'write full misses', 'write total',
                      f'writes to exported object{s}', f'total to/from exported object{s}',
                      'writes to cache', 'total to/from cache',
                      f'writes to core{s}', f'total to/from core{s}']

        for io_class, core, file_size in zip(tested_io_classes, cycle(cores), sizes):
            cache.purge_cache()
            drop_caches()
            cache.reset_counters()

            with TestRun.step(f"Testing core {core.core_id} with IO class {io_class.id}."):

                size_in_blocks = round(file_size.get_value(Unit.Blocks4096))

                TestRun.LOGGER.info("Run fio.")
                fio = fio_params(core, file_size, direct=False if io_class.id != 22 else True)
                fio.run()
                sync()
                drop_caches()

                TestRun.LOGGER.info("Check statistics.")
                dev = core if per_core else cache
                stats = dev.get_statistics_flat(
                    io_class.id, [StatsFilter.usage, StatsFilter.req, StatsFilter.blk])
                stats_perc = dev.get_statistics_flat(io_class.id, [StatsFilter.usage],
                                                     percentage_val=True)

                # TODO: need proper values for pass-through reads, pass-through writes,
                #  serviced requests, total requests and check correctness of other values

                for name, value in stats.items():
                    value = round(value) if type(value) is float \
                        else round(value.get_value(Unit.Blocks4096))

                    expected_value = size_in_blocks if name in stats_size else 0
                    check_value(name, value, expected_value)

                for name, value in stats_perc.items():
                    occupancy = 100 * (size_in_blocks / cache_size)
                    expected_value = 100 if name == 'clean' else \
                        occupancy if name == 'occupancy' else 0
                    epsilon_percentage = 0.5 if name in ('clean', 'occupancy') else 0
                    check_perc_value(name, value, expected_value, epsilon_percentage)

                saved_stats.append(dev.get_statistics_flat(io_class.id,
                                                           [StatsFilter.conf, StatsFilter.usage]))

    with TestRun.step("Stop and load cache back."):
        [core.unmount() for core in cores]
        cache.stop()
        cache = casadm.load_cache(cache_device)

    with TestRun.step(f"Validate IO class statistics per {'core' if per_core else 'cache'} - "
                      f"shall be the same as before stop."):
        stats = []
        for io_class, core in zip(tested_io_classes, cycle(cores)):
            dev = core if per_core else cache
            stats.append(dev.get_statistics_flat(io_class.id,
                                                 [StatsFilter.conf, StatsFilter.usage]))

        for saved_stat, stat, core, io_class in \
                zip(saved_stats, stats, cycle(cores), tested_io_classes):
            TestRun.LOGGER.info(f"Testing {f'core {core.core_id}' if per_core else 'cache'} "
                                f"with IO class {io_class.id}.")
            for name, saved_value, value in zip(stat.keys(), saved_stat.values(), stat.values()):
                value = round(value.get_value(Unit.Blocks4096)) if type(value) is Size else value
                saved_value = round(saved_value.get_value(Unit.Blocks4096)) \
                    if type(saved_value) is Size else saved_value
                check_value(name, value, saved_value)

    with TestRun.step("Sum (except free) all values from statistics and "
                      "compare it with statistics for cache."):
        occupancy = sum([core.get_statistics().usage_stats.occupancy for core in cores])
        dirty = sum([core.get_statistics().usage_stats.dirty for core in cores])
        clean = sum([core.get_statistics().usage_stats.clean for core in cores])
        cores_stats = [occupancy, dirty, clean]

        cache_occupancy = cache.get_statistics().usage_stats.occupancy
        cache_dirty = cache.get_statistics().usage_stats.dirty
        cache_clean = cache.get_statistics().usage_stats.clean
        cache_stats = [cache_occupancy, cache_dirty, cache_clean]

        for name, cores_sum, cache_stat in zip(
                ('occupancy', 'dirty', 'clean'), cores_stats, cache_stats):
            check_value(name, cores_sum, cache_stat)


def get_sizes(io_classes):
    sizes = [Size(int(re.search(r"\d+", io_class.rule).group()), Unit.Byte)
             for io_class in io_classes[:-2]]
    sizes.extend([sizes[-1] + Size(100, Unit.MebiByte), Size(1, Unit.Blocks4096)])

    return sizes


def check_value(name, actual_value, expected_value):
    if actual_value != expected_value:
        TestRun.LOGGER.error(f"Bad {name} value. "
                             f"Expected: {expected_value}, actual: {actual_value}.")
    else:
        TestRun.LOGGER.info(f"Proper {name} value: {actual_value}.")


def check_perc_value(name, actual_value, expected_value, epsilon_percentage):
    if abs(expected_value - actual_value) > epsilon_percentage:
        TestRun.LOGGER.error(f"Bad {name} percentage value. "
                             f"Expected: {expected_value}, actual: {actual_value}.")
    else:
        TestRun.LOGGER.info(f"Proper {name} percentage value: {actual_value}.")


def fio_params(core, size, direct=False):
    name = f"{core.mount_point}/{round(size.get_value())}{'_direct' if direct else ''}"
    fio = Fio().create_command() \
        .io_engine(IoEngine.libaio) \
        .read_write(ReadWrite.write) \
        .io_depth(1) \
        .block_size(Size(1, Unit.Blocks4096)) \
        .num_jobs(1) \
        .direct(direct) \
        .file_size(size) \
        .target(name)

    return fio
