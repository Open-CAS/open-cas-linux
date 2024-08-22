#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

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
    prepare_cas_instance,
    get_fuzz_config,
    get_cmd,
    run_cmd_and_validate,
)
from tests.security.fuzzy.kernel.fuzzy_with_io.common.common import (
    get_basic_workload,
    mount_point,
)

io_class_file_path = "/root/Fuzzy/ioclass.csv"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_io_class_config_priority(
    cache_mode, cache_line_size, cleaning_policy, unaligned_io, use_io_scheduler
):
    """
    title: Fuzzy test for IO class configuration content – IO class priority.
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong IO class priority
        in IO class configuration file.
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
        PeachFuzzer.generate_config(get_fuzz_config("uint.yml"))
        parameters = PeachFuzzer.generate_peach_fuzzer_parameters(TestRun.usr.fuzzy_iter_count)

    for index, parameter in TestRun.iteration(
        enumerate(parameters), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            if not TestRun.executor.check_if_process_exists(fio_pid):
                raise Exception("Fio is not running.")

            parameter = parameter.decode("ascii", "ignore")
            io_class.priority = parameter
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
                value_name="Priority",
                is_valid=__is_valid(parameter),
            )


def __is_valid(parameter):
    if parameter == "":
        return True

    try:
        value = int(parameter)
    except ValueError:
        return False

    if -1 <= value <= 255:
        return True

    return False
