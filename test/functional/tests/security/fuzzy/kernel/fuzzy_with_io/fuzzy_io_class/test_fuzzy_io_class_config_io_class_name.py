#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import re
import pytest

from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    CleaningPolicy,
    UnalignedIo,
    KernelParameters,
    UseIoScheduler,
)
from api.cas.cli import load_io_classes_cmd
from api.cas.ioclass_config import IoClass, Operator
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from tests.security.fuzzy.kernel.common.common import (
    get_cmd,
    run_cmd_and_validate,
    prepare_cas_instance,
    get_fuzz_config,
)
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import (
    get_basic_workload,
    mount_point,
)

io_class_file_path = "/root/Fuzzy/ioclass.csv"
parametrized_keywords = [
    "directory",
    "file_name_prefix",
    "extension",
    "process_name",  # string - based
    "file_size",
    "io_class",
    "lba",
    "pid",
    "file_offset",
    "request_size",  # number - based
    "io_direction",
]
parameterless_keywords = ["metadata", "direct", "done"]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_io_class_config_io_class_name(
    cache_mode, cache_line_size, cleaning_policy, unaligned_io, use_io_scheduler
):
    """
    title: Fuzzy test for IO class configuration content – IO class name.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong IO class name in
        IO class configuration file.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """
    with TestRun.step(
        "Start cache with configuration and add core device, make filesystem and mount it"
    ):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache, core = prepare_cas_instance(
            cache_device=cache_disk,
            core_device=core_disk,
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
            cleaning_policy=cleaning_policy,
            mount_point=mount_point,
        )

    with TestRun.step("Run fio in background"):
        fio = get_basic_workload(mount_point)
        fio_pid = fio.run_in_background()
        if not TestRun.executor.check_if_process_exists(fio_pid):
            raise Exception("Fio is not running.")

        io_class = IoClass(class_id=1, rule=f"file_size:{Operator.le.name}:97517568", priority=255)

    with TestRun.step("Prepare PeachFuzzer"):
        PeachFuzzer.generate_config(get_fuzz_config("string.yml"))
        parameters = PeachFuzzer.generate_peach_fuzzer_parameters(TestRun.usr.fuzzy_iter_count)
        parameters = __get_fuzzed_parameters(parameters)

    for index, parameter in TestRun.iteration(
        enumerate(parameters), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            if not TestRun.executor.check_if_process_exists(fio_pid):
                raise Exception("Fio is not running.")

            io_class.rule = parameter
            IoClass.save_list_to_config_file(
                ioclass_list=[io_class],
                add_default_rule=False,
                ioclass_config_path=io_class_file_path,
            )
            cmd = get_cmd(
                command=load_io_classes_cmd(str(core.cache_id), io_class_file_path),
                param=parameter,
            )
            run_cmd_and_validate(
                cmd=cmd,
                value_name="Io Class name",
                is_valid=__is_valid(parameter),
            )


def __get_fuzzed_parameters(parameters):
    fuzzed_parameters = []

    for index, param in enumerate(parameters):
        if index < TestRun.usr.fuzzy_iter_count // 10:
            param = param.decode("ascii", "ignore")
            i = index % (len(parametrized_keywords) + len(parameterless_keywords) + 1)
            match i:
                case 1:
                    fuzzed_parameters.append(f"directory:{param}")
                case 2:
                    fuzzed_parameters.append(f"extension:{param}")
                case 3:
                    fuzzed_parameters.append(f"process_name:{param}")
                case 4:
                    fuzzed_parameters.append(f"file_name_prefix:{param}")
                case 5:
                    fuzzed_parameters.append(__get_condition("file_size", i, param))
                case 6:
                    fuzzed_parameters.append(__get_condition("io_class", i, param))
                case 7:
                    fuzzed_parameters.append(__get_condition("request_size", i, param))
                case 8:
                    fuzzed_parameters.append(__get_condition("lba", i, param))
                case 9:
                    fuzzed_parameters.append(__get_condition("pid", i, param))
                case 10:
                    fuzzed_parameters.append(__get_condition("file_offset", i, param))
                case 11:
                    fuzzed_parameters.append(f"metadata{'' if i % 10 == 0 else param}")
                case 12:
                    fuzzed_parameters.append(f"direct{'' if i % 10 == 0 else param}")
                case 13:
                    fuzzed_parameters.append(f"done{'' if i % 10 == 0 else param}")
                case 14:
                    fuzzed_parameters.append(f"io_direction:{param}")
                case _:
                    fuzzed_parameters.append(param)
        else:
            number_of_condition = random.randint(1, 12)
            ands_probability = random.randint(0, number_of_condition) / number_of_condition
            max_length_of_single_condition = 200

            short_names = [
                param for param in fuzzed_parameters if len(param) < max_length_of_single_condition
            ]

            expression = ""
            for i in range(number_of_condition):
                expression += short_names[random.randint(0, len(short_names) - 1)]
                expression += "&" if random.randint(1, 10) < ands_probability * 10 else "|"

            expression += short_names[random.randint(0, len(short_names) - 1)]
            fuzzed_parameters.append(expression)
    return fuzzed_parameters


def __get_condition(class_type: str, i: int, param: str):
    if i % 4 == 0:
        return f"{class_type}:{param}"
    operators = [operator.name for operator in list(Operator)]

    return f"{class_type}:{operators[i % len(operators)]}:{param}"


def __is_valid(value: str):
    # IO Class name length should be less than 1024
    if len(value) > 1024:
        return False

    # Only characters allowed in IO class name are low (the first 128) ascii characters,
    # excluding control characters, comma and quotation mark.
    if any(True for char in value if ord(char) > 126 or ord(char) < 32 or ord(char) in [34, 44]):
        return False

    single_params = re.split("[|]|&", value)
    for param in single_params:
        if not __validate_single_condition(param):
            return False
    return True


def __validate_single_condition(value: str):
    if value in parameterless_keywords:
        return True

    condition_key = ""
    condition_value = ""

    for key in parametrized_keywords:
        if f"{key}:" in value:
            condition_key = key
            condition_value = value.split(":", maxsplit=1)[-1]
            break

    if condition_key is None:
        return False

    if condition_key in ["directory", "file_name_prefix", "extension", "process_name"]:
        if 0 < len(condition_value) <= 255:
            return True
    elif condition_key == "io_direction":
        return condition_value in ["read", "write"]
    elif condition_key in [
        "file_size",
        "io_class",
        "lba",
        "pid",
        "file_offset",
        "request_size",
    ]:
        #  key:number case
        if ":" not in condition_value:
            try:
                size = int(condition_value)
            except ValueError:
                return False
            else:
                if 0 <= size <= pow(2, 64) - 1:
                    return True
                else:
                    return False

        #  key:keyword:number case where keyword is [ "gt", "ge", "lt", "le", "eq" ]
        key_value = condition_value.split(":")
        if len(key_value) != 2:
            return False
        if key_value[0] not in [operator.name for operator in list(Operator)]:
            return False

        try:
            size = int(key_value[1])
        except ValueError:
            return False
        else:
            if 0 <= size <= pow(2, 64) - 1:
                return True
            else:
                return False

    return False
