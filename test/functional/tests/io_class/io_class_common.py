#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas import casadm
from api.cas import ioclass_config
from api.cas.cache_config import (
    CacheLineSize,
    CacheMode,
    CleaningPolicy,
    SeqCutOffPolicy,
)
from core.test_run import TestRun
from test_tools.dd import Dd
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils.os_utils import Udev, sync
from test_utils.os_utils import drop_caches, DropCachesMode
from test_utils.size import Size, Unit


ioclass_config_path = "/tmp/opencas_ioclass.conf"
mountpoint = "/tmp/cas1-1"


def prepare(
    cache_size=Size(10, Unit.GibiByte),
    core_size=Size(40, Unit.GibiByte),
    cache_mode=CacheMode.WB,
    cache_line_size=CacheLineSize.LINE_4KiB,
    default_allocation="0.00"
):
    ioclass_config.remove_ioclass_config()
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    cache_device.create_partitions([cache_size])
    core_device.create_partitions([core_size])

    cache_device = cache_device.partitions[0]
    core_device = core_device.partitions[0]

    TestRun.LOGGER.info(f"Starting cache")
    cache = casadm.start_cache(
        cache_device, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True
    )

    Udev.disable()
    TestRun.LOGGER.info(f"Setting cleaning policy to NOP")
    casadm.set_param_cleaning(cache_id=cache.cache_id, policy=CleaningPolicy.nop)
    TestRun.LOGGER.info(f"Adding core device")
    core = casadm.add_core(cache, core_dev=core_device)
    TestRun.LOGGER.info(f"Setting seq cutoff policy to never")
    core.set_seq_cutoff_policy(SeqCutOffPolicy.never)
    ioclass_config.create_ioclass_config(
        add_default_rule=False, ioclass_config_path=ioclass_config_path
    )
    # To make test more precise all workload except of tested ioclass should be
    # put in pass-through mode
    ioclass_config.add_ioclass(
        ioclass_id=ioclass_config.DEFAULT_IO_CLASS_ID,
        eviction_priority=ioclass_config.DEFAULT_IO_CLASS_PRIORITY,
        allocation=default_allocation,
        rule=ioclass_config.DEFAULT_IO_CLASS_RULE,
        ioclass_config_path=ioclass_config_path,
    )

    output = TestRun.executor.run(f"mkdir -p {mountpoint}")
    if output.exit_code != 0:
        raise Exception(f"Failed to create mountpoint")

    return cache, core


def get_io_class_occupancy(cache, io_class_id, percent=False):
    return get_io_class_usage(cache, io_class_id, percent).occupancy


def get_io_class_dirty(cache, io_class_id):
    return get_io_class_usage(cache, io_class_id).dirty


def get_io_class_usage(cache, io_class_id, percent=False):
    return cache.get_io_class_statistics(
        io_class_id=io_class_id, percentage_val=percent
    ).usage_stats


def run_io_dir(path, size_4k, offset=0):
    dd = (
        Dd()
        .input("/dev/zero")
        .output(f"{path}")
        .count(size_4k)
        .block_size(Size(1, Unit.Blocks4096))
        .seek(offset)
    )
    TestRun.LOGGER.info(f"{dd}")
    output = dd.run()
    if output.exit_code != 0:
        TestRun.fail(f"Failed to execute dd.\n {output.stdout}\n{output.stderr}")
    sync()
    drop_caches(DropCachesMode.ALL)


def run_io_dir_read(path):
    dd = Dd().output("/dev/null").input(f"{path}")
    output = dd.run()
    if output.exit_code != 0:
        TestRun.fail(f"Failed to execute dd.\n {output.stdout}\n{output.stderr}")
    sync()
    drop_caches(DropCachesMode.ALL)


def run_fio_count(core, blocksize, num_ios):
    (
        Fio()
        .create_command()
        .target(core)
        .io_engine(IoEngine.libaio)
        .read_write(ReadWrite.randread)
        .block_size(blocksize)
        .direct()
        .file_size(Size(10, Unit.GibiByte))
        .num_ios(num_ios)
        .run()
    )
