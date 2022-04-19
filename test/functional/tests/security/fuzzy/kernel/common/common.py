#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import os
import posixpath
from typing import Callable

import yaml

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, KernelParameters, CleaningPolicy
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit


def get_fuzz_config(config_name: str):
    with open(posixpath.join(os.path.dirname(__file__), f"../../config/{config_name}")) as cfg:
        fuzz_config = yaml.safe_load(cfg)

    return fuzz_config


def prepare_cas_instance(cache_disk, core_disk, cache_mode: CacheMode = None,
                         cache_line_size: CacheLineSize = None,
                         kernel_params: KernelParameters = KernelParameters(),
                         cleaning_policy: CleaningPolicy = None, mount_point: str = None):
    #  Change cleaning policy to default for Write Policy different than WB
    if cleaning_policy:
        cleaning_policy = CleaningPolicy.DEFAULT if cache_mode != CacheMode.WB \
            else cleaning_policy

    cache_disk.create_partitions([Size(400, Unit.MebiByte)])
    cache_device = cache_disk.partitions[0]
    cache = casadm.start_cache(cache_device, cache_mode, cache_line_size, 1, True,
                               kernel_params=kernel_params)
    if cleaning_policy:
        cache.set_cleaning_policy(cleaning_policy)

    if mount_point:
        core_disk.create_filesystem(Filesystem.ext4)
        core = cache.add_core(core_disk)
        core.mount(mount_point)
    else:
        core = cache.add_core(core_disk)

    return cache, core


def run_cmd_and_validate(cmd, value_name: str, valid_values: list,
                         post_process_param_func: Callable = None):
    TestRun.LOGGER.info(f"{value_name}: {cmd.param}")
    TestRun.LOGGER.info(f"Encoded command: {cmd.command}")
    output = TestRun.executor.run(cmd.command)
    param = cmd.param
    if post_process_param_func:
        param = post_process_param_func(param)

    if output.exit_code == 0 and param not in valid_values:
        TestRun.LOGGER.error(f" {param} value is not valid")
    elif output.exit_code != 0 and param in valid_values:
        TestRun.LOGGER.error(f" {param} value is valid but command returned with "
                             f"{output.exit_code} exit code")
