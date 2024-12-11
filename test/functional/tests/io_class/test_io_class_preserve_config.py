#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, ioclass_config
from api.cas.ioclass_config import IoClass
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from type_def.size import Size, Unit
from tests.io_class.io_class_common import (
    compare_io_classes_list,
    generate_and_load_random_io_class_config,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_preserve_configuration():
    """
    title: Preserve IO class configuration after load.
    description: |
        Check Open CAS ability to preserve IO class configuration
        after starting CAS with load option.
    pass_criteria:
        - No system crash
        - Cache loads successfully
        - IO class configuration is the same before and after reboot
    """
    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(150, Unit.MebiByte)])
        core_device.create_partitions([Size(300, Unit.MebiByte)])

        cache_device = cache_device.partitions[0]
        core_device = core_device.partitions[0]

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_device, force=True)

    with TestRun.step("Display IO class configuration – shall be only Unclassified IO class."):
        default_io_class = [
            IoClass(
                ioclass_config.DEFAULT_IO_CLASS_ID,
                ioclass_config.DEFAULT_IO_CLASS_RULE,
                ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
                allocation="1.00",
            )
        ]
        actual = cache.list_io_classes()
        compare_io_classes_list(default_io_class, actual)

    with TestRun.step("Add core device."):
        cache.add_core(core_device)

    with TestRun.step(
        "Create and load configuration file for 33 IO classes with random names, "
        "allocation and priority values."
    ):
        generated_io_classes = generate_and_load_random_io_class_config(cache)

    with TestRun.step("Display IO class configuration – shall be the same as created."):
        actual = cache.list_io_classes()
        compare_io_classes_list(generated_io_classes, actual)

    with TestRun.step("Stop cache."):
        cache.stop()

    with TestRun.step(
        "Load cache and check IO class configuration - shall be the same as created."
    ):
        cache = casadm.load_cache(cache_device)
        actual = cache.list_io_classes()
        compare_io_classes_list(generated_io_classes, actual)

    with TestRun.step("Reboot platform."):
        TestRun.executor.reboot()

    with TestRun.step(
        "Load cache and check IO class configuration - shall be the same as created."
    ):
        cache = casadm.load_cache(cache_device)
        actual = cache.list_io_classes()
        compare_io_classes_list(generated_io_classes, actual)
