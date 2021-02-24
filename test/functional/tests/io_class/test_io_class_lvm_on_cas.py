#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm, ioclass_config
from api.cas.cache_config import CacheMode
from api.cas.ioclass_config import IoClass
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from storage_devices.lvm import Lvm, LvmConfiguration
from test_tools import fs_utils
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.size import Size, Unit

mount_point = "/mnt/"
io_target = "/mnt/test"


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_lvm_on_cas():
    """
        title: IO class for CAS device behind LVM.
        description: Validate the ability of CAS to cache IO class when CAS device is used as LVM.
        pass_criteria:
          - Create CAS device and LVM on top of it successfully.
          - Loading IO class configuration successfully.
          - Running FIO for file size from IO class from 11 to 21 successfully.
          - Increasing proper statistics as expected.
    """

    with TestRun.step(f"Create CAS device."):
        cache_dev = TestRun.disks['cache']
        core_dev = TestRun.disks['core']
        cache_dev.create_partitions([Size(20, Unit.GibiByte)])
        core_dev.create_partitions([Size(20, Unit.GibiByte)])

        cache = casadm.start_cache(cache_dev.partitions[0], CacheMode.WB, force=True)
        core = cache.add_core(core_dev.partitions[0])

    with TestRun.step("Create LVM on CAS device."):
        lvm_filters = ["a/.*/", "r|/dev/sd*|", "r|/dev/hd*|", "r|/dev/xvd*|", "r/disk/", "r/block/",
                       "r|/dev/nvme*|"]

        config = LvmConfiguration(lvm_filters,
                                  pv_num=1,
                                  vg_num=1,
                                  lv_num=1,
                                  cache_num=1,
                                  cas_dev_num=1)

        lvms = Lvm.create_specific_lvm_configuration(core, config)
        lvm = lvms[0]

    with TestRun.step("Create filesystem for LVM and mount it."):
        lvm.create_filesystem(Filesystem.ext4)
        lvm.mount(mount_point)

    with TestRun.step("Prepare and load IO class config."):
        io_classes = IoClass.csv_to_list(fs_utils.read_file("/etc/opencas/ioclass-config.csv"))
        # remove two firs elements/lines: unclassified and metadata
        io_classes.pop(1)
        io_classes.pop(0)
        IoClass.save_list_to_config_file(io_classes, add_default_rule=False)
        cache.load_io_class(ioclass_config.default_config_file_path)

    with TestRun.step("Run fio for file size from IO class from 11 to 21 "
                      "and check that correct statistics increased."):
        file_size = Size(2, Unit.KibiByte)

        for io_class in io_classes:
            if io_class.id < 11 or io_class.id > 21:
                continue

            TestRun.LOGGER.info(f"IO Class ID: {io_class.id}, class name: {io_class.rule}")
            cache.reset_counters()

            TestRun.LOGGER.info(f"Run FIO with verification on LVM [IO class ID {io_class.id}]")
            (Fio().create_command()
             .target(io_target)
             .read_write(ReadWrite.randwrite)
             .io_engine(IoEngine.libaio)
             .io_depth(16)
             .file_size(file_size)
             .verification_with_pattern()
             .write_percentage(100)
             .block_size(Size(1, Unit.Blocks512))
             .run())

            TestRun.LOGGER.info(f"Checking statistics [IO class ID {io_class.id}]")

            for io_class_i in io_classes:
                class_stats = cache.get_io_class_statistics(io_class_i.id)
                total_requests_io_class = class_stats.request_stats.requests_total

                if io_class_i.id == io_class.id:
                    if total_requests_io_class == 0:
                        TestRun.LOGGER.error(f"[WB] 'Total requests'=0 (but should increased) "
                                             f"for IO Class {io_class.id} [{io_class.rule}]: "
                                             f"{total_requests_io_class}")
                        TestRun.executor.run(f"ls -la {mount_point}*")
                    else:
                        TestRun.LOGGER.info(f"[WB] 'Total requests' for IO Class {io_class.id} "
                                            f"[{io_class.rule}]: {total_requests_io_class}")
                        continue

                if total_requests_io_class > 0:
                    TestRun.LOGGER.error(f"[WB] 'Total requests' increased (not expected) "
                                         f"for IO Class {io_class_i.id} [{io_class_i.rule}]: "
                                         f"{total_requests_io_class}")
                    TestRun.executor.run(f"ls -la {mount_point}*")
                else:
                    TestRun.LOGGER.info(f"[WB] 'Total requests' for IO Class {io_class_i.id} "
                                        f"[{io_class_i.rule}]: {total_requests_io_class}")

            if file_size < Size(256, Unit.MebiByte):
                file_size *= 4
            else:
                file_size = Size(1100, Unit.MebiByte)

            fs_utils.remove(io_target)

    with TestRun.step("Remove LVMs."):
        TestRun.executor.run(f"umount {mount_point}")
        Lvm.remove_all()
