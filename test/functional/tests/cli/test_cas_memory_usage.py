#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cas_module import CasModule
from core.test_run import TestRun
from test_utils.size import Unit, Size
from test_utils.os_utils import (allocate_memory,
                                 defaultize_memory_affecting_functions,
                                 disable_memory_affecting_functions,
                                 drop_caches,
                                 get_mem_free,
                                 is_kernel_module_loaded,
                                 load_kernel_module,
                                 unload_kernel_module,
                                 unmount_ramfs,
                                 get_dut_cpu_number,
                                 DropCachesMode)


@pytest.mark.os_dependent
def test_cas_module_memory_usage():
    """
        title: Validate OpenCAS kernel module memory usage.
        description: |
          Check that OpenCAS kernel module memory usage is in acceptable limits.
        pass_criteria: |
          - Loaded OpenCAS kernel module should not consume more than 140% of total memory
          calculated by requirement formula:
          7.5 MiB * active CPUs number
    """
    with TestRun.step("Disable caching and memory over-committing."):
        disable_memory_affecting_functions()
        drop_caches(DropCachesMode.ALL)

    with TestRun.step("Measure memory usage without OpenCAS module."):
        if is_kernel_module_loaded(CasModule.cache.value):
            unload_kernel_module(CasModule.cache.value)
            unload_kernel_module(CasModule.disk.value)
        available_mem_before_cas = get_free_memory()

    with TestRun.step("Load OpenCAS module"):
        output = load_kernel_module(CasModule.cache.value)
        if output.exit_code != 0:
            TestRun.fail("Cannot load OpenCAS module!")

    with TestRun.step("Measure memory usage with OpenCAS module."):
        available_mem_with_cas = get_free_memory()
        memory_used_by_cas = available_mem_before_cas - available_mem_with_cas
        TestRun.LOGGER.info(
            f"OpenCAS module uses {memory_used_by_cas.get_value(Unit.MiB):.2f} MiB of DRAM."
        )

    with TestRun.step("Validate amount of memory used by OpenCAS module"):
        expected_memory_used = Size(7.5 * get_dut_cpu_number(), Unit.MiB)
        TestRun.LOGGER.info(
            f"Expected module memory consumption:"
            f" {expected_memory_used.get_value(Unit.MiB):.2f} MiB of DRAM."
        )
        requirement_fulfillment_ratio = (
            memory_used_by_cas.get_value() / expected_memory_used.get_value()
        )
        TestRun.LOGGER.info(f"Actual to expected usage ratio: {requirement_fulfillment_ratio:.2f}")
        if requirement_fulfillment_ratio > 1.1:
            if requirement_fulfillment_ratio < 1.4:
                TestRun.LOGGER.warning("Memory usage corresponds to required limit "
                                       "(between 110-140% of expected value)")
            else:
                TestRun.LOGGER.error("Memory usage exceeded required limit "
                                     "(over 140% of expected value)")
        elif requirement_fulfillment_ratio < 0.8:
            TestRun.LOGGER.warning("Memory usage is strangely small (below 80% of expected value)")
        else:
            TestRun.LOGGER.info("Memory usage corresponds to required limit")


@pytest.mark.os_dependent
def test_insufficient_memory_for_cas_module():
    """
        title: Negative test of ability to load OpenCAS kernel module with insufficient memory.
        description: |
          Check that OpenCAS kernel module won’t be loaded in case not enough memory is available.
        pass_criteria:
          - Loading OpenCAS kernel module returns error.
    """
    with TestRun.step("Disable caching and memory over-committing."):
        disable_memory_affecting_functions()
        drop_caches()

    with TestRun.step("Measure memory usage without OpenCAS module."):
        if is_kernel_module_loaded(CasModule.cache.value):
            unload_kernel_module(CasModule.cache.value)
        available_mem_before_cas = get_mem_free()

    with TestRun.step("Load OpenCAS module"):
        output = load_kernel_module(CasModule.cache.value)
        if output.exit_code != 0:
            TestRun.fail("Cannot load OpenCAS module!")

    with TestRun.step("Measure memory usage with OpenCAS module."):
        available_mem_with_cas = get_mem_free()
        memory_used_by_cas = available_mem_before_cas - available_mem_with_cas
        TestRun.LOGGER.info(
            f"OpenCAS module uses {memory_used_by_cas.get_value(Unit.MiB):.2f} MiB of DRAM."
        )

    with TestRun.step("Unload OpenCAS module."):
        unload_kernel_module(CasModule.cache.value)

    with TestRun.step("Allocate memory leaving not enough memory for OpenCAS module."):
        memory_to_leave = memory_used_by_cas * (3 / 4)
        try:
            allocate_memory(get_mem_free() - memory_to_leave)
        except Exception as ex:
            TestRun.LOGGER.error(f"{ex}")

    with TestRun.step(
            "Try to load OpenCAS module and check if error message is printed on failure."
    ):
        output = load_kernel_module(CasModule.cache.value)
        if output.stderr and output.exit_code != 0:
            memory_left = get_mem_free()
            TestRun.LOGGER.info(
                f"Memory left for OpenCAS module: {memory_left.get_value(Unit.MiB):0.2f} MiB."
            )
            TestRun.LOGGER.info(f"Cannot load OpenCAS module as expected.\n{output.stderr}")
        else:
            TestRun.LOGGER.error("Loading OpenCAS module successfully finished, but should fail.")

    with TestRun.step("Set memory options to default"):
        unmount_ramfs()
        defaultize_memory_affecting_functions()
