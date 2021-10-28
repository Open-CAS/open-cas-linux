#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
from datetime import timedelta
import pytest
from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.optane, DiskType.nand, DiskType.sata]))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.require_plugin("vdbench")
def test_trim_stress(cache_mode, cache_line_size):
    """
        title: Trim support on cache devices in different cache modes stress test.
        description: |
          Stress test validating the ability of CAS to handle trim requests in different modes,
          on different filesystem types.
        pass_criteria:
          - No kernel bug.
          - Cache should still work correctly.
    """

    cores_number = 4
    mount_point = "/mnt"

    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(1, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(1, Unit.GibiByte)] * cores_number)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
        cores = []
        for d in core_devices:
            cores.append(cache.add_core(d))

    with TestRun.step("Create filesystem and mount CAS devices."):
        directories = []
        for counter, core in enumerate(cores):
            core.create_filesystem(Filesystem(counter % len(Filesystem)))
            mount_dir = os.path.join(mount_point, str(counter + 1))
            directories.append(mount_dir)
            core.mount(mount_dir, ["discard"])

    with TestRun.step("Run I/O workload."):
        for _ in TestRun.iteration(range(1, 7)):
            run_vdbench(directories)

    with TestRun.step("Stop CAS."):
        for c in cores:
            c.unmount()
            c.remove_core()
        cache.stop()


def run_vdbench(directories):
    vdbench = TestRun.plugin_manager.get_plugin('vdbench')
    config = f"data_errors=1,validate=yes,messagescan=no,create_anchors=yes\n" \
             f"fsd=default,depth=4,width=5,files=10,sizes=" \
             f"(1k,10,2k,10,4k,10,8k,10,16k,10,32k,10,64k,10,128k,10,256k,10,512k,10)\n"

    for i, dir in enumerate(directories):
        config += f"fsd=fsd{i},anchor={dir}\n"

    config += f"\nfwd=fwd1,fsd=fsd*," \
              f"fileio=(random),fileselect=random,threads=32," \
              f"xfersizes=(512,10,1k,10,2k,10,4k,10,8k,10,16k,10,32k,10,64k,10," \
              f"128k,10,256k,10)\nrd=rd1,fwd=fwd*,fwdrate=max,format=yes," \
              f"interval=5,operations=(read,write,open,close,getattr,setattr)"
    vdbench.create_config(config, run_time=timedelta(minutes=5))
    if vdbench.run():
        TestRun.LOGGER.info("VDBench finished with status zero.")
    else:
        TestRun.LOGGER.error("VDBench finished with non-zero status.")
