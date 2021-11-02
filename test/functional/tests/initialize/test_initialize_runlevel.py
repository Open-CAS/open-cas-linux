#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import pytest
import time
from api.cas import casadm, casadm_parser
from api.cas.cache_config import CacheMode
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskTypeLowerThan, DiskTypeSet, DiskType
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils import os_utils
from test_utils.os_utils import Runlevel
from test_utils.size import Size, Unit


mount_point = "/mnt/test"


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("runlevel", [Runlevel.runlevel5, Runlevel.runlevel3])
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_init_reboot_runlevels(runlevel, cache_mode):
    """
        title: Initialize CAS devices after reboot
        description: |
          Verify that CAS init script starts cache properly after reboot in different runlevels.
        pass_criteria:
          - Cache should be loaded successfully after reboot.
    """
    with TestRun.step(f"Set runlevel to {runlevel.value}."):
        os_utils.change_runlevel(runlevel)

    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(2, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]
        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(1, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        core = cache.add_core(core_dev)

    with TestRun.step("Create CAS init config based on running configuration."):
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Make filesystem on CAS device and mount it."):
        core.create_filesystem(Filesystem.xfs)
        core.mount(mount_point)

    with TestRun.step("Start writing file to CAS."):
        fio = Fio().create_command()\
            .file_name(os.path.join(mount_point, "test_file"))\
            .read_write(ReadWrite.randwrite)\
            .io_engine(IoEngine.sync)\
            .num_jobs(1).direct()\
            .file_size(Size(30, Unit.GibiByte))

        fio.run_in_background()
        os_utils.sync()
        os_utils.drop_caches()

        time.sleep(10)
        TestRun.executor.run_expect_success("pgrep fio")

    with TestRun.step("Reboot machine during writing a file."):
        TestRun.executor.reboot()

    with TestRun.step("Check if cache was properly started at boot time"):
        # Wait for CAS to load after boot
        time.sleep(60)
        caches = casadm_parser.get_caches()
        if len(caches) == 1:
            TestRun.LOGGER.info("Cache started properly at boot time.")
        else:
            TestRun.LOGGER.error("Cache did not start properly at boot time.")

    with TestRun.step("Stop cache and set default runlevel."):
        if len(caches) != 0:
            casadm.stop_all_caches()
        os_utils.change_runlevel(Runlevel.runlevel3)
        TestRun.executor.reboot()
