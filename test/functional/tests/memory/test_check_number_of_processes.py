#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.os_utils import (get_number_of_processors_from_cpuinfo,
                                 get_number_of_processes)
from test_utils.size import Size, Unit

cleaning_threads_expected = 1
management_thread_expected = 1
fill_threads_expected = 0
metadata_updater_threads_expected = 1


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_check_number_of_processes():
    """
        title: Check the number of processes created by CAS.
        description: |
          For created CAS device check number of IO threads, cleaning threads, management threads,
           fill threads, metadata updater threads.
        pass_criteria:
          - Successful CAS creation.
          - Successful validation of each thread number.
    """
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(2, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Check number of IO threads."):
        number_of_processors = get_number_of_processors_from_cpuinfo()
        io_threads_actual = get_number_of_processes("cas_io")

        validate_threads_number("IO threads", io_threads_actual, number_of_processors)

    with TestRun.step("Check number of cleaning threads."):
        cleaning_threads_actual = get_number_of_processes("cas_cl")

        validate_threads_number("cleaning threads", cleaning_threads_actual,
                                cleaning_threads_expected)

    with TestRun.step("Check number of management threads."):
        management_threads_actual = get_number_of_processes("cas_mngt")

        validate_threads_number("management threads", management_threads_actual,
                                management_thread_expected)

    with TestRun.step("Check number of fill threads."):
        fill_threads_actual = get_number_of_processes("cas_wb")
        validate_threads_number("fill threads", fill_threads_actual, fill_threads_expected)

    with TestRun.step("Check number of metadata updater threads."):
        metadata_updater_threads_actual = get_number_of_processes("cas_mu")

        validate_threads_number("metadata updater threads", metadata_updater_threads_actual,
                                metadata_updater_threads_expected)


def validate_threads_number(threads_name, threads_number, threads_expected):
    if threads_number == threads_expected:
        TestRun.LOGGER.info(f"Number of {threads_name} correct.")
    else:
        TestRun.LOGGER.error(f"Number of {threads_name} incorrect. Actual: {threads_number}, "
                             f"expected: {threads_expected}.")
