#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
import random
from datetime import timedelta

from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, CpusAllowedPolicy, ErrorFilter
from test_tools.fio.fio_patterns import Pattern
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_utils import remove
from test_utils.size import Unit, Size


def get_unique_patterns():
    return set(list(Pattern.__members__.values()))


def mix_patterns():
    patterns = list(get_unique_patterns())
    random.shuffle(patterns)
    return patterns


exp_obj_size = Size(50, Unit.GibiByte)
exp_obj_number = 4
unique_patterns_number = len(get_unique_patterns())
runtime = timedelta(hours=2)
mount_point = '/mnt/cas'


@pytest.mark.os_dependent
@pytest.mark.parametrize(
    "pattern", [Pattern.cyclic, Pattern.sequential]
)
@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_data_integrity_single_pattern(cache_mode, pattern):
    """
        title:
          Data integrity test with different write patterns with 2 hours duration time
        description: |
          Run fio with single pattern on each core and verify if there are no write errors.
        pass_criteria:
            - System does not crash.
            - Fio does not return any errors.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([exp_obj_size * (exp_obj_number / 4)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([exp_obj_size] * exp_obj_number)

    with TestRun.step(f"Start cache in {cache_mode} mode"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)

    with TestRun.step(f"Add all core devices to cache."):
        cores = []
        for core_part in core_dev.partitions:
            core_part.create_filesystem(Filesystem.ext3, True)
            cores.append(cache.add_core(core_part))

    with TestRun.step("Mount all cores"):
        fio_targets = []
        for i, core in enumerate(cores):
            core_mount_point = f"{mount_point}{cache.cache_id}-{core.core_id}"
            core.mount(f"{core_mount_point}")
            fio_targets.append(f"{core_mount_point}/test_file")

    with TestRun.step(f"Run fio with {pattern.name} pattern."):
        fio = prepare_unified_fio(fio_targets, pattern)
        fio_output = fio.run()

    with TestRun.step("Check for fio errors."):
        fio_errors = fio_output[0].total_errors()
        if fio_errors:
            TestRun.LOGGER.error(f"Found {fio_errors} errors in fio output")

    with TestRun.step("Delete test files."):
        for file in fio_targets:
            remove(file, True, True, True)

    with TestRun.step("Unmount all cores."):
        for core in cores:
            core.unmount()


def prepare_unified_fio(targets, data_pattern):
    fio = (
        _prepare_fio()
        .num_jobs(exp_obj_number)
        .verification_with_pattern(data_pattern.value)
    )

    for i, target in enumerate(targets):
        (
            fio.add_job(f"job_{i+1}")
            .target(target)
            .size(0.95 * exp_obj_size)
        )

    return fio


def prepare_mixed_fio(targets, data_patterns):
    fio = (
        _prepare_fio()
        .num_jobs(unique_patterns_number)
    )

    for i, target in enumerate(targets):
        (
            fio.add_job(f"job_{i+1}")
            .target(target)
            .size(0.95 * exp_obj_size)
            .verification_with_pattern(data_patterns[i].value)
        )

    return fio


def _prepare_fio():
    fio = (
        Fio().create_command()
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.readwrite)
        .write_percentage(90)
        .block_size(Size(1, Unit.Blocks4096))
        .continue_on_error(ErrorFilter.verify)
        .cpus_allowed_policy(CpusAllowedPolicy.split)
        .run_time(runtime)
        .time_based()
        .direct()
    )

    return fio
