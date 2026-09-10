#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import secrets
from api.cas import ioclass_config
from test_utils.os_utils import Udev
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite, VerifyMethod
from api.cas import casadm
from api.cas.cache_config import CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

number_of_cores = 4
ioclass_config_path = "/tmp/excludeFs.csv"
random_pattern_A = "0x" + secrets.token_hex(16)
random_pattern_B = "0x" + secrets.token_hex(16)


@pytest.mark.parametrize("cache_mode", CacheMode)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.nand]))
@pytest.mark.require_plugin("scsi_debug")
def test_cas_metadata_invalidate(cache_mode):
    """
    title: "Verification if metadata is invalidated after removing core device", "Verification if
    Open CAS do not keep any information from previous removed core device and do not use them
    for new core", pass_criteria: - CAS device do not keep any information from previous removed
    core device and do not use them for new core
    """
    with TestRun.step("Create 4 partition for core devices"):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(1, Unit.GibiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions(number_of_cores * [Size(50, Unit.GibiByte)])
        core_part = core_dev.partitions

    with TestRun.step("Start CAS with configuration, add 4 cores and create fs (ext3, ext4, "
                      "xfs) for 3 core devices"):
        cache = casadm.start_cache(cache_part, force=True)
        core_partitions = []
        mount_point_dict = dict()
        for index, filesystem in enumerate(Filesystem):
            core_partitions.append(cache.add_core(core_part[index]))
            core_partitions[index].create_filesystem(filesystem)
            mount_point = f"/mnt/CasMetadataInvalidate/{index}"
            core_partitions[index].mount(mount_point)
            mount_point_dict[mount_point] = core_partitions[index]
        unmounted_device = core_part[-1]
        unmounted_core = cache.add_core(unmounted_device)

    with TestRun.step("Create fio on 4 devices (added to CAS)"):
        fio = __create_fio_jobs(cache_mode, ReadWrite.write, random_pattern_A, mount_point_dict,
                                unmounted_core.path)
        fio.run()

    with TestRun.step("Remove all 4 cores"):
        for mounted_core in core_partitions:
            mounted_core.unmount()
        for core in [*mount_point_dict.values(), unmounted_core]:
            casadm.remove_core(cache.cache_id, core.core_id)

    with TestRun.step("Mount partitions with filesystem, without raw partition"):
        for mount_point, core in mount_point_dict.items():
            core.core_device.mount(mount_point)

    with TestRun.step("Overwrite files with pattern B, including the one "
                      "with raw partition"):
        fio = __create_fio_jobs(cache_mode, ReadWrite.write, random_pattern_B, mount_point_dict,
                                unmounted_device.path)
        fio.run()

    with TestRun.step("Add 4 cores and mount partitions"):
        Udev.disable()
        ioclass_config.create_ioclass_config(
            add_default_rule=False
        )
        ioclass_config.add_ioclass(
            ioclass_id=1,
            allocation=0,
            rule="metadata",
            eviction_priority=1,
        )
        cache.load_io_class(ioclass_config.default_config_file_path)
        for mount_point, core in mount_point_dict.items():
            core.core_device.unmount()
            cache.add_core(core.core_device)
            core.mount(mount_point)
        cache.add_core(unmounted_device)

    with TestRun.step("Read and verify pattern B"):
        fio = __create_fio_jobs(cache_mode, ReadWrite.read, random_pattern_B,
                                mount_point_dict,
                                unmounted_core.path, verify_only=True)
        fio.run()

    with TestRun.step("Check in statistics, that all reads are missed"):
        cache_hit_percentage = cache.get_statistics(percentage_val=True).request_stats.read.hits
        if cache_hit_percentage > 0:
            TestRun.fail(f"Read hits percentage: {cache_hit_percentage}")
        else:
            TestRun.LOGGER.info(f"Read hits percentage: {cache_hit_percentage}")


def __create_fio_jobs(write_policy, fio_write, pattern, mount_point_dict, unmounted_device_path,
                      verify_only=False):
    fio = (Fio().create_command()
           .io_engine(IoEngine.libaio)
           .block_size(Size(1, Unit.Blocks4096), Size(1, Unit.Blocks512))
           .size(Size(200, Unit.MebiByte))
           .direct(False)
           .read_write(fio_write)
           .verify(VerifyMethod.pattern)
           .verify_pattern(pattern)
           .do_verify(write_policy == CacheMode.WA)
           .allow_mounted_write()
           .rand_seed(TestRun.random_seed)
           )

    if verify_only:
        fio.verify_only()

    for index, (mount_point, device) in enumerate(mount_point_dict.items()):
        fio.add_job(f"job_{index}").directory(mount_point).target(f"fio_test_file_{index}")
    fio.add_job().target(unmounted_device_path)

    return fio
