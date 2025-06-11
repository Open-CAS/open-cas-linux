#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import datetime
import pytest

from storage_devices.lvm import Lvm, LvmConfiguration
from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools import initramfs
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from type_def.size import Size, Unit
from tests.volumes.common import get_test_configuration, validate_configuration


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_many_cores_on_many_lvms():
    """
    title: Test for CAS creation with lvms as cores: 1 cache, 16 lvms, 16 cores.
    description: |
        Validation of LVM support, CAS with 1 cache and 16 lvms as 16 cores.
    pass_criteria:
      - LVMs created successfully.
      - CAS devices created successfully.
      - FIO with verification ran successfully.
      - Configuration after reboot match configuration before.
    """
    with TestRun.step(f"Prepare devices."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']
        cache_device.create_partitions([Size(1, Unit.GibiByte)])
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_device.partitions[0]
        core_dev = core_device.partitions[0]

    with TestRun.step("Configure LVM to use device filters."):
        LvmConfiguration.set_use_devices_file(False)

    with TestRun.step("Create LVMs."):
        config = LvmConfiguration(lvm_filters=[],
                                  pv_num=1,
                                  vg_num=1,
                                  lv_num=16,
                                  )

        lvms = Lvm.create_specific_lvm_configuration([core_dev], config)

    with TestRun.step(f"Create CAS device."):
        cache = casadm.start_cache(cache_dev, force=True)
        cores = []
        for lvm in lvms:
            cores.append(cache.add_core(lvm))

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
        for lvm in cores:
            fio_run.add_job().target(lvm).size(lvm.size)
        fio_run.run()

    with TestRun.step("Flush buffers"):
        for core in cores:
            TestRun.executor.run_expect_success(f"hdparm -f {core.path}")

    with TestRun.step("Create init config from running configuration"):
        config_before_reboot, devices_before = get_test_configuration()

    with TestRun.step("Reboot system."):
        TestRun.executor.reboot()

    with TestRun.step("Validate running configuration"):
        validate_configuration(config_before_reboot, devices_before)

    with TestRun.step("Run FIO with verification on LVM."):
        fio_run.run()

    with TestRun.step("Remove CAS devices."):
        casadm.remove_all_detached_cores()
        casadm.stop_all_caches()

    with TestRun.step("Remove LVMs."):
        Lvm.remove_all()
