#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import datetime
import pytest

from storage_devices.lvm import Lvm, LvmConfiguration
from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import initramfs
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from types.size import Size, Unit
from tests.volumes.common import get_test_configuration, lvm_filters


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_many_lvms_on_single_core():
    """
        title: Test for LVM creation on CAS device - many lvms on single core.
        description: |
          Validation of LVM support, many LVMs (16) created on CAS device (1 cache, 1 core).
        pass_criteria:
          - CAS devices created successfully.
          - LVMs created successfully.
          - FIO with verification ran successfully.
          - Configuration after reboot match configuration before.
    """
    with TestRun.step(f"Create CAS device."):
        cache_dev = TestRun.disks['cache']
        core_dev = TestRun.disks['core']
        cache_dev.create_partitions([Size(8, Unit.GibiByte)])
        core_dev.create_partitions([Size(8, Unit.GibiByte)])

        cache = casadm.start_cache(cache_dev.partitions[0], force=True)
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Configure LVM to use device filters."):
        LvmConfiguration.set_use_devices_file(False)

    with TestRun.step("Add CAS device type to the LVM config file."):
        LvmConfiguration.add_block_device_to_lvm_config("cas")

    with TestRun.step("Create LVMs on CAS device."):
        config = LvmConfiguration(lvm_filters,
                                  pv_num=1,
                                  vg_num=1,
                                  lv_num=2,)

        lvms = Lvm.create_specific_lvm_configuration(core, config)

    with TestRun.step("Update initramfs"):
        initramfs.update()

    with TestRun.step("Run FIO with verification on LVM."):
        fio_run = (Fio().create_command()
                   .read_write(ReadWrite.randrw)
                   .io_engine(IoEngine.sync)
                   .io_depth(1)
                   .time_based()
                   .run_time(datetime.timedelta(seconds=180))
                   .do_verify()
                   .verify(VerifyMethod.md5)
                   .block_size(Size(1, Unit.Blocks4096)))
        for lvm in lvms:
            fio_run.add_job().target(lvm).size(lvm.size)
        fio_run.run()

    with TestRun.step("Flush buffers"):
        for lvm in lvms:
            TestRun.executor.run_expect_success(f"hdparm -f {lvm.path}")

    with TestRun.step("Create init config from running configuration"):
        config_before_reboot, devices_before = get_test_configuration()

    with TestRun.step("Reboot system."):
        TestRun.executor.reboot()

    with TestRun.step("Validate running configuration"):
        config_after_reboot, devices_after = get_test_configuration()

        if config_after_reboot == config_before_reboot:
            TestRun.LOGGER.info(f"Configuration is as expected")
        else:
            TestRun.LOGGER.info(f"config before reboot: {config_before_reboot}")
            TestRun.LOGGER.info(f"config after reboot: {config_after_reboot}")
            TestRun.LOGGER.error(f"Configuration changed after reboot")

        if devices_after == devices_before:
            TestRun.LOGGER.info(f"Device list is as expected")
        else:
            TestRun.LOGGER.info(f"Devices before: {devices_before}")
            TestRun.LOGGER.info(f"Devices after: {devices_after}")
            TestRun.LOGGER.error(f"Device list changed after reboot")

    with TestRun.step("Run FIO with verification on LVM."):
        fio_run.run()

    with TestRun.step("Remove LVMs."):
        Lvm.remove_all()
