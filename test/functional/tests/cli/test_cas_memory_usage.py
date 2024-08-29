#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cas_module import CasModule
from core.test_run import TestRun
from test_utils.size import Unit
from test_utils.os_utils import (allocate_memory,
                                 disable_memory_affecting_functions,
                                 drop_caches,
                                 get_mem_free,
                                 is_kernel_module_loaded,
                                 load_kernel_module,
                                 unload_kernel_module,
                                 )


@pytest.mark.os_dependent
def test_insufficient_memory_for_cas_module():
    """
    title: Negative test for the ability of CAS to load the kernel module with insufficient memory.
    description: |
      Check that the CAS kernel module won’t be loaded if enough memory is not available
    pass_criteria:
      - CAS module cannot be loaded with not enough memory.
      - Loading CAS with not enough memory returns error.
    """

    with TestRun.step("Disable caching and memory over-committing"):
        disable_memory_affecting_functions()
        drop_caches()

    with TestRun.step("Measure memory usage without OpenCAS module"):
        if is_kernel_module_loaded(CasModule.cache.value):
            unload_kernel_module(CasModule.cache.value)
        available_mem_before_cas = get_mem_free()

    with TestRun.step("Load CAS module"):
        load_kernel_module(CasModule.cache.value)

    with TestRun.step("Measure memory usage with CAS module"):
        available_mem_with_cas = get_mem_free()
        memory_used_by_cas = available_mem_before_cas - available_mem_with_cas
        TestRun.LOGGER.info(
            f"OpenCAS module uses {memory_used_by_cas.get_value(Unit.MiB):.2f} MiB of DRAM."
        )

    with TestRun.step("Unload CAS module"):
        unload_kernel_module(CasModule.cache.value)

    with TestRun.step("Allocate memory, leaving not enough memory for CAS module"):
        memory_to_leave = get_mem_free() - (memory_used_by_cas * (3 / 4))
        allocate_memory(memory_to_leave)
        TestRun.LOGGER.info(
            f"Memory left for OpenCAS module: {get_mem_free().get_value(Unit.MiB):0.2f} MiB."
        )

    with TestRun.step(
            "Try to load OpenCAS module and check if correct error message is printed on failure"
    ):
        output = load_kernel_module(CasModule.cache.value)
        if output.stderr and output.exit_code != 0:
            TestRun.LOGGER.info(f"Cannot load OpenCAS module as expected.\n{output.stderr}")
        else:
            TestRun.LOGGER.error("Loading OpenCAS module successfully finished, but should fail.")
