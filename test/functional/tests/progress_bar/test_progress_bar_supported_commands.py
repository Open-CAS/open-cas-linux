#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import casadm, cli
from api.cas.cache_config import CacheMode, CleaningPolicy, SeqCutOffPolicy
from api.cas.progress_bar import check_progress_bar
from core.test_run_utils import TestRun
from storage_devices.disk import DiskTypeSet, DiskType
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.size import Size, Unit


progress_bar_cmd_cache = [cli.stop_cmd, cli.flush_cache_cmd, cli.script_purge_cache_cmd]
progress_bar_cmd_core = [cli.flush_core_cmd, cli.remove_core_cmd, cli.script_purge_core_cmd,
                         cli.script_remove_core_cmd]
progress_bar_cmd_other = [cli.set_cache_mode_cmd]
progress_bar_cmd = progress_bar_cmd_cache + progress_bar_cmd_core + progress_bar_cmd_other


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_progress_bar_supported_commands():
    """
        title: Progress bar validation for all supported commands - buffered IO, WB mode.
        description: Validate the ability of the CAS to display data flashing progress
                     for direct IO in WB mode.
        pass_criteria:
          - progress bar appear correctly
          - progress only increase
    """
    with TestRun.step("Prepare devices."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(5, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(2, Unit.GibiByte)] * 4)
        core_devices = core_disk.partitions

    for command in TestRun.iteration(progress_bar_cmd):

        with TestRun.step("Start cache in Write-Back mode and add cores."):
            cache = casadm.start_cache(cache_dev, cache_mode=CacheMode.WB, force=True)
            cores = [cache.add_core(dev) for dev in core_devices]
            cache.set_cleaning_policy(CleaningPolicy.nop)
            cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Run fio on all OpenCAS devices."):
            fio = (Fio().create_command()
                   .size(Size(1, Unit.GibiByte))
                   .read_write(ReadWrite.randwrite)
                   .io_engine(IoEngine.sync)
                   .direct())
            for i, core in enumerate(cores):
                fio.add_job(f"core{i}").target(core.path)
            fio.run()

        with TestRun.step("Run command and check progress."):
            if command in progress_bar_cmd_cache:
                cmd = command(str(cache.cache_id))
            elif command in progress_bar_cmd_core:
                cmd = command(str(cache.cache_id), str(cores[0].core_id))
            elif command in progress_bar_cmd_other:
                cmd = command(str(CacheMode.WT.name).lower(), str(cache.cache_id), 'yes')

            check_progress_bar(cmd)

        with TestRun.step("Stopping cache."):
            casadm.stop_all_caches()
