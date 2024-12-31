#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_tools.os_tools import sync, drop_caches
from test_tools.udev import Udev
from type_def.size import Unit, Size
from tests.io_class.io_class_common import prepare


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_wlth():
    """
    title: Test for `wlth` classification rule
    description: |
        Test CAS ability to cache IO based on 'write-life-time-hints' classification rule.
    pass_criteria:
     - IO with wlth is cached
     - IO without wlth is not cached
    """
    with TestRun.step(f"Start cache with one core with NOP and disabled seq cutoff"):
        cache, core = prepare()

    with TestRun.step(f"Add wlth based classification rules"):
        cached_ioclass_id = 10
        ioclass_config.create_ioclass_config(add_default_rule=False)
        ioclass_config.add_ioclass(
            ioclass_id=0,
            eviction_priority=22,
            allocation="0",
            rule=f"unclassified",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )
        ioclass_config.add_ioclass(
            ioclass_id=cached_ioclass_id,
            eviction_priority=22,
            allocation="1.00",
            rule=f"wlth:eq:4&done",
            ioclass_config_path=ioclass_config.default_config_file_path,
        )

    with TestRun.step(f"Load ioclass config file"):
        casadm.load_io_classes(
            cache_id=cache.cache_id, file=ioclass_config.default_config_file_path
        )

    with TestRun.step(f"Reset counters"):
        sync()
        drop_caches()
        Udev.disable()
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step(f"Trigger IO with a write life time hint"):
        # Fio adds hints only to direct IO. Even if `write_hint` param isn't provided, direct IO
        # has assigned a hint by default
        io_count = 12345
        io_size = Size(io_count, Unit.Blocks4096)
        bs = Size(1, Unit.Blocks4096)
        (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(io_size)
            .block_size(bs)
            .write_hint("long")
            .read_write(ReadWrite.write)
            .target(core.path)
            .direct()
            .run()
        )

    with TestRun.step(f"Trigger IO without write life time hint"):
        (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(io_size)
            .offset(io_size)
            .block_size(bs)
            .read_write(ReadWrite.write)
            .target(core.path)
            .run()
        )
        sync()
        drop_caches()

    with TestRun.step(f"Check stats"):
        default_io_class_stats = core.get_io_class_statistics(io_class_id=0)
        wlth_io_class_stats = core.get_io_class_statistics(io_class_id=10)

        if int(wlth_io_class_stats.request_stats.requests_serviced) != io_count:
            TestRun.LOGGER.error(
                f"There should be {io_count} serviced requests in wlth based io class but the "
                f"actual number is {wlth_io_class_stats.request_stats.requests_serviced}"
            )
        if int(wlth_io_class_stats.request_stats.pass_through_writes) != 0:
            TestRun.LOGGER.error(
                f"There should be 0 pass through writes in wlth based io class but the actual "
                f"number is {wlth_io_class_stats.request_stats.pass_through_writes}"
            )

        if int(default_io_class_stats.request_stats.requests_serviced) != 0:
            TestRun.LOGGER.error(
                f"There should be 0 serviced requests in the default io class but the actual "
                f"number is {default_io_class_stats.request_stats.requests_serviced}"
            )
        if int(default_io_class_stats.request_stats.pass_through_writes) != io_count:
            TestRun.LOGGER.error(
                f"There should be {io_count} pass through writes in the default io class but the "
                f"actual number is {default_io_class_stats.request_stats.pass_through_writes}"
            )
