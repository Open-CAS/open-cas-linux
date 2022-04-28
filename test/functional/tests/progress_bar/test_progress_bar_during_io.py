#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta
from time import sleep

import pytest
from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.progress_bar import check_progress_bar
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_progress_bar_during_io():
    """
        title: Progress bar validation during IO.
        description: Validate the ability of the CAS to flush data after intensive FIO workload.
        pass_criteria:
          - progress bar appear correctly
          - progress only increase
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(5, Unit.GibiByte)] * 4)
        core_devices = core_disk.partitions

    with TestRun.step("Start cache in Write-Back mode and add cores."):
        cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(dev) for dev in core_devices]
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

    with TestRun.step("Start fio on all OpenCAS devices."):
        fio = (Fio().create_command()
               .time_based()
               .run_time(timedelta(minutes=25))
               .read_write(ReadWrite.write)
               .block_size(Size(1, Unit.Blocks4096))
               .direct()
               .io_engine(IoEngine.libaio))
        for i, core in enumerate(cores):
            fio.add_job(f"core{i}").target(core.path)
        fio_pid = fio.run_in_background()

        TestRun.LOGGER.info("Wait 8 minutes.")
        sleep(480)

    with TestRun.step("Run command and check progress."):
        cmd = cli.flush_cache_cmd(str(cache.cache_id))
        check_progress_bar(cmd)

    with TestRun.step("Wait for fio to finish."):
        TestRun.executor.wait_cmd_finish(fio_pid)
