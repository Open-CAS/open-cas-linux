#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cas_module import CasModule
from core.test_run import TestRun
from test_utils.size import Unit
from test_utils.os_utils import (allocate_memory,
                                 defaultize_memory_affecting_functions,
                                 disable_memory_affecting_functions,
                                 drop_caches,
                                 get_free_memory,
                                 is_kernel_module_loaded,
                                 load_kernel_module,
                                 unload_kernel_module,
                                 unmount_ramfs)


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

    with TestRun.step("Unload OpenCAS module."):
        unload_kernel_module(CasModule.cache.value)
        unload_kernel_module(CasModule.disk.value)

    with TestRun.step("Allocate memory leaving not enough memory for OpenCAS module."):
        memory_to_leave = memory_used_by_cas * (3 / 4)
        try:
            allocate_memory(get_free_memory() - memory_to_leave)
        except Exception as ex:
            TestRun.LOGGER.error(f"{ex}")

    with TestRun.step(
            "Try to load OpenCAS module and check if error message is printed on failure."
    ):
        output = load_kernel_module(CasModule.cache.value)
        if output.stderr and output.exit_code != 0:
            memory_left = get_free_memory()
            TestRun.LOGGER.info(
                f"Memory left for OpenCAS module: {memory_left.get_value(Unit.MiB):0.2f} MiB."
            )
            TestRun.LOGGER.info(f"Cannot load OpenCAS module as expected.\n{output.stderr}")
        else:
            TestRun.LOGGER.error("Loading OpenCAS module successfully finished, but should fail.")

    with TestRun.step("Set memory options to default"):
        unmount_ramfs()
        defaultize_memory_affecting_functions()
