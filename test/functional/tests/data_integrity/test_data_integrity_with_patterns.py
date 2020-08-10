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
