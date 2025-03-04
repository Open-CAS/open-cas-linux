#
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import datetime
import pytest

from storage_devices.lvm import Lvm, LvmConfiguration
from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from type_def.size import Size, Unit
from tests.volumes.common import get_test_configuration, lvm_filters, validate_configuration


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_many_lvms_on_many_cores_by_serial():
    """
    title: Test for LVM creation on cached volumes using their serial - many lvms on many cores.
    description: |
        Validate if LVMs based on exported objects combined into one volume group are created
        successfully using cached volume's serial after system reboot.
    pass_criteria:
      - exported objects created successfully
      - LVMs created successfully
      - FIO with verification ran successfully
      - Configuration after reboot match configuration before
    """
    with TestRun.step("Prepare devices."):
        cache_dev = TestRun.disks["cache"]
        core_dev = TestRun.disks["core"]
        cache_dev.create_partitions([Size(2, Unit.GibiByte)])
        core_dev.create_partitions([Size(2, Unit.GibiByte)] * 4)

        cache = casadm.start_cache(cache_dev.partitions[0], force=True)
        cores = [cache.add_core(core_part) for core_part in core_dev.partitions]

    with TestRun.step("Configure LVM to use devices file."):
        LvmConfiguration.set_use_devices_file(True)

    with TestRun.step("Add CAS device type to the LVM config file."):
        LvmConfiguration.add_block_device_to_lvm_config("cas")

    with TestRun.step("Create LVMs on cached volumes."):
        config = LvmConfiguration(lvm_filters,
                                  pv_num=4,
                                  vg_num=1,
                                  lv_num=16,)

        lvms = Lvm.create_specific_lvm_configuration(cores, config)

    with TestRun.step("Run FIO with verification on LVM."):
        fio_run = (Fio().create_command()
                   .read_write(ReadWrite.randrw)
                   .io_engine(IoEngine.sync)
                   .io_depth(1)
                   .time_based()
                   .run_time(datetime.timedelta(seconds=30))
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
        validate_configuration(config_before_reboot, devices_before)

    with TestRun.step("Run FIO with verification on LVM."):
        fio_run.run()

    with TestRun.step("Remove LVMs."):
        Lvm.remove_all()
