#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import datetime
import pytest

from api.cas.init_config import InitConfig, opencas_conf_path
from storage_devices.lvm import Lvm, LvmConfiguration

from api.cas import casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, VerifyMethod
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core1", DiskTypeLowerThan("cache"))
@pytest.mark.require_disk("core2", DiskTypeLowerThan("cache"))
def test_many_lvms_on_many_cores():
    """
        title: Test for LVM creation on CAS: 1 cache, 4 cores, 4 lvms.
        description: |
          Validation of LVM support, LVMs created (4) on CAS device (1 cache, 4 cores).
        pass_criteria:
          - CAS devices created successfully.
          - LVMs created successfully.
          - FIO with verification ran successfully.
          - Configuration after reboot match configuration before.
    """
    with TestRun.step(f"Create CAS device."):
        cache_device = TestRun.disks['cache']
        core_devices = [TestRun.disks['core1'],
                        TestRun.disks['core2']]

        cache_device.create_partitions([Size(20, Unit.GibiByte)])

        core_partitions = []
        for core_dev in core_devices:
            core_dev.create_partitions([Size(10, Unit.GibiByte)] * 2)
            core_partitions.append(core_dev.partitions[0])
            core_partitions.append(core_dev.partitions[1])

        cache = casadm.start_cache(cache_device.partitions[0], force=True)
        cores = []
        for core_dev in core_partitions:
            cores.append(cache.add_core(core_dev))

    with TestRun.step("Create LVMs on CAS device."):
        lvm_filters = ["a/.*/", "r|/dev/sd*|", "r|/dev/hd*|", "r|/dev/xvd*|", "r/disk/", "r/block/",
                       "r|/dev/nvme*|"]

        config = LvmConfiguration(lvm_filters,
                                  pv_num=4,
                                  vg_num=4,
                                  lv_num=4,
                                  cache_num=1,
                                  cas_dev_num=len(cores))

        lvms = Lvm.create_specific_lvm_configuration(cores, config)

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

    with TestRun.step("Remove LVMs and clean up config changes."):
        Lvm.remove_all()
        LvmConfiguration.remove_filters_from_config()


def get_block_devices_list():
    cmd = f"lsblk -l | awk '{{print $1}}' | grep -v loop"
    devices = TestRun.executor.run_expect_success(cmd).stdout
    devices_list = devices.splitlines()
    devices_list.sort()

    return devices_list


def get_test_configuration():
    InitConfig.create_init_config_from_running_configuration()
    config_output = TestRun.executor.run(f"cat {opencas_conf_path}")
    devices = get_block_devices_list()

    return config_output.stdout, devices
