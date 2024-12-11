#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#
import base64
import os
import posixpath
from collections import namedtuple
from typing import List

import yaml

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize, KernelParameters, CleaningPolicy
from core.test_run import TestRun
from test_tools.disk_utils import Filesystem
from type_def.size import Size, Unit


def get_fuzz_config(config_name: str):
    with open(posixpath.join(os.path.dirname(__file__), f"../../config/{config_name}")) as cfg:
        fuzz_config = yaml.safe_load(cfg)

    return fuzz_config


def get_device_fuzz_config(device_paths: List[str]):
    if len(device_paths) == 0:
        raise Exception("device_paths parameter cannot be empty list")

    device_base_config = get_fuzz_config("device.yml")
    device_base_config[0]["attributes"]["value"] = device_paths[0]
    if len(device_paths) > 1:
        other_valid_devices = {
            "name": "Hint",
            "attributes": {"name": "ValidValues", "value": ";".join(device_paths[1:])},
        }
        device_base_config[0]["children"].append(other_valid_devices)

    return device_base_config


def prepare_cas_instance(
    cache_device,
    core_device,
    cache_mode: CacheMode = None,
    cache_line_size: CacheLineSize = None,
    kernel_params: KernelParameters = KernelParameters(),
    cleaning_policy: CleaningPolicy = None,
    mount_point: str = None,
    create_partition=True,
):
    #  Change cleaning policy to default for Write Policy different than WB
    if cleaning_policy:
        cleaning_policy = CleaningPolicy.DEFAULT if cache_mode != CacheMode.WB else cleaning_policy

    if create_partition is True:
        cache_device.create_partitions([Size(400, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]

    cache = casadm.start_cache(
        cache_device, cache_mode, cache_line_size, 1, True, kernel_params=kernel_params
    )
    if cleaning_policy:
        cache.set_cleaning_policy(cleaning_policy)

    if mount_point:
        core_device.create_filesystem(Filesystem.ext4)
        core = cache.add_core(core_device)
        core.mount(mount_point)
    else:
        core = cache.add_core(core_device)

    return cache, core


def run_cmd_and_validate(cmd, value_name: str, is_valid: bool):
    cmd_prefix = b"echo "
    cmd_suffix = b" | base64 --decode | sh"
    TestRun.LOGGER.info(f"{value_name}: {cmd.param}")
    TestRun.LOGGER.info(f"Command: {cmd.command}")

    encoded_command = cmd_prefix + base64.b64encode(cmd.command) + cmd_suffix

    TestRun.LOGGER.info(f"Executed (encoded) command: {encoded_command}")
    output = TestRun.executor.run(encoded_command)

    if output.exit_code == 0 and not is_valid:
        TestRun.LOGGER.error(
            f"{cmd.param} value is not valid\n"
            f"stdout: {output.stdout}\n"
            f"stderr: {output.stderr}"
        )
    elif output.exit_code != 0 and is_valid:
        TestRun.LOGGER.error(
            f"{cmd.param} value is valid but command returned with "
            f"{output.exit_code} exit code\n"
            f"stdout: {output.stdout}\n"
            f"stderr: {output.stderr}"
        )

    return output


def get_cmd(command, param):
    FuzzedCommand = namedtuple("Command", ["param", "command"])
    return FuzzedCommand(param, command.encode("ascii"))
