#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2023-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cas_module import CasModule
from api.cas.cli_messages import check_stderr_msg, attach_not_enough_memory
from connection.utils.output import CmdException
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from type_def.size import Unit, Size
from test_tools.os_tools import (drop_caches,
                                 is_kernel_module_loaded,
                                 load_kernel_module,
                                 unload_kernel_module,
                                 )
from test_tools.memory import disable_memory_affecting_functions, get_mem_free, allocate_memory, \
    get_mem_available, unmount_ramfs


@pytest.mark.os_dependent
def test_insufficient_memory_for_cas_module():
    """
    title: Load CAS kernel module with insufficient memory
    description: |
        Negative test for the ability to load the CAS kernel module with insufficient memory.
    pass_criteria:
      - CAS kernel module cannot be loaded with not enough memory.
      - Loading CAS kernel module with not enough memory returns error.
    """

    with TestRun.step("Disable caching and memory over-committing"):
        disable_memory_affecting_functions()
        drop_caches()

    with TestRun.step("Measure memory usage without CAS kernel module"):
        if is_kernel_module_loaded(CasModule.cache.value):
            unload_kernel_module(CasModule.cache.value)
        available_mem_before_cas = get_mem_free()

    with TestRun.step("Load CAS kernel module"):
        load_kernel_module(CasModule.cache.value)

    with TestRun.step("Measure memory usage with CAS kernel module"):
        available_mem_with_cas = get_mem_free()
        memory_used_by_cas = available_mem_before_cas - available_mem_with_cas
        TestRun.LOGGER.info(
            f"CAS kernel module uses {memory_used_by_cas.get_value(Unit.MiB):.2f} MiB of DRAM."
        )

    with TestRun.step("Unload CAS kernel module"):
        unload_kernel_module(CasModule.cache.value)

    with TestRun.step("Allocate memory, leaving not enough memory for CAS module"):
        memory_to_leave = get_mem_free() - (memory_used_by_cas * (3 / 4))
        allocate_memory(memory_to_leave)
        TestRun.LOGGER.info(
            f"Memory left for CAS kernel module: {get_mem_free().get_value(Unit.MiB):0.2f} MiB."
        )

    with TestRun.step(
            "Try to load CAS kernel module and check if correct error message is printed on failure"
    ):
        output = load_kernel_module(CasModule.cache.value)
        if output.stderr and output.exit_code != 0:
            TestRun.LOGGER.info(f"Cannot load CAS kernel module as expected.\n{output.stderr}")
        else:
            TestRun.LOGGER.error("Loading CAS kernel module successfully finished, but should fail.")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_attach_cache_min_ram():
    """
    title: Test attach cache with insufficient memory.
    description: |
        Check for valid message when attaching cache with insufficient memory.
    pass_criteria:
      - CAS attach operation fail due to insufficient RAM.
      - No system crash.
    """

    with TestRun.step("Prepare devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_dev.partitions[0]
        cache_dev2 = TestRun.disks["cache2"]
        core_dev = TestRun.disks["core"]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_dev, force=True)
        cache.add_core(core_dev)

    with TestRun.step("Detach cache"):
        cache.detach()

    with TestRun.step("Set RAM workload"):
        disable_memory_affecting_functions()
        allocate_memory(get_mem_available() - Size(100, Unit.MegaByte))

    with TestRun.step("Try to attach cache"):
        try:
            TestRun.LOGGER.info(
                f"There is {get_mem_available().unit.MebiByte.value} available memory left"
            )
            cache.attach(device=cache_dev2, force=True)
            TestRun.LOGGER.error(
                f"Cache attached not as expected."
                f"{get_mem_available()} is enough memory to complete operation")

        except CmdException as exc:
            check_stderr_msg(exc.output, attach_not_enough_memory)

    with TestRun.step("Unlock RAM memory"):
        unmount_ramfs()

