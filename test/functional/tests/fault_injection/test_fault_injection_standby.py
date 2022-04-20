#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from collections import namedtuple
import random

from api.cas import casadm
from api.cas import dmesg
from api.cas.cli import casadm_bin
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.size import Size, Unit
from api.cas.cli_messages import check_stderr_msg, missing_param, disallowed_param
from api.cas.cache_config import CacheLineSize, CacheMode
from api.cas.cli import standby_activate_cmd, standby_load_cmd
from api.cas.ioclass_config import IoClass
from test_tools.dd import Dd
from test_utils.os_utils import sync
from test_utils.filesystem.file import File


block_size = Size(1, Unit.Blocks512)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_activate_corrupted():
    """
    title: Activate cache instance on corrupted metadata
    description: |
      Initialize standby cache, populate it with corrupted metadata, detach and try to activate.
    pass_criteria:
      - Kernel panic doesn't occur
    """
    with TestRun.step("Prepare devices for the cache and core."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(200, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device = core_device.partitions[0]

    with TestRun.step("Prepare metadata dump"):
        cache_id = 1
        cls = CacheLineSize.LINE_32KiB
        md_dump = prepare_md_dump(cache_device, core_device, cls, cache_id)

    for offset in get_offsets_to_corrupt(md_dump.size, block_size):

        with TestRun.step("Prepare standby instance"):
            cache = casadm.standby_init(
                cache_dev=cache_device,
                cache_line_size=int(cls.value.value / Unit.KibiByte.value),
                cache_id=cache_id,
                force=True,
            )

        with TestRun.step(f"Corrupt {block_size} on the offset {offset*block_size}"):
            corrupted_md = prepare_corrupted_md(md_dump, offset, block_size)

        with TestRun.step(f"Copy corrupted metadata to the passive instance"):
            Dd().input(corrupted_md.full_path).output(f"/dev/cas-cache-{cache_id}").run()
            sync()

        with TestRun.step(f"Standby detach"):
            cache.standby_detach()

        with TestRun.step("Try to activate cache instance"):
            output = TestRun.executor.run(
                standby_activate_cmd(cache_dev=cache_device.path, cache_id=str(cache_id))
            )

        with TestRun.step("Per iteration cleanup"):
            cache.stop()
            corrupted_md.remove(force=True, ignore_errors=True)

    with TestRun.step("Test cleanup"):
        md_dump.remove()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_load_corrupted():
    """
    title: Standby-load corrupted metadata
    description: |
      Try to load standby instance from corrupted metadata
    pass_criteria:
      - Kernel panic doesn't occur
    """
    with TestRun.step("Prepare devices for the cache and core."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(200, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device = core_device.partitions[0]

    with TestRun.step("Prepare metadata dump"):
        cache_id = 1
        cls = CacheLineSize.LINE_32KiB
        md_dump = prepare_md_dump(cache_device, core_device, cls, cache_id)

    for offset in get_offsets_to_corrupt(md_dump.size, block_size):

        with TestRun.step(f"Corrupt {block_size} on the offset {offset*block_size}"):
            corrupted_md = prepare_corrupted_md(md_dump, offset, block_size)

        with TestRun.step(f"Copy corrupted metadata to the cache-to-be device"):
            Dd().input(corrupted_md.full_path).output(cache_device.path).run()
            sync()

        with TestRun.step("Try to load cache instance"):
            output = TestRun.executor.run(standby_load_cmd(cache_dev=cache_device.path))

        with TestRun.step("Per iteration cleanup"):
            if output.exit_code:
                casadm.stop_all_caches()
            corrupted_md.remove(force=True, ignore_errors=True)

    with TestRun.step("Test cleanup"):
        md_dump.remove()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_activate_corrupted_after_dump():
    """
    title: Activate cache instance on metadata corrupted after the detach
    description: |
      Initialize standby cache, populate it with metadata, detach cache, corrupt metadata
      on the cache-to-be device and try to activate.
    pass_criteria:
      - Kernel panic doesn't occur
    """
    with TestRun.step("Prepare devices for the cache and core."):
        cache_device = TestRun.disks["cache"]
        cache_device.create_partitions([Size(200, Unit.MebiByte)])
        cache_device = cache_device.partitions[0]
        core_device = TestRun.disks["core"]
        core_device.create_partitions([Size(500, Unit.MebiByte)])
        core_device = core_device.partitions[0]

    with TestRun.step("Prepare metadata dump"):
        cache_id = 1
        cls = CacheLineSize.LINE_32KiB
        md_dump = prepare_md_dump(cache_device, core_device, cls, cache_id)

    for offset in get_offsets_to_corrupt(md_dump.size, block_size):

        with TestRun.step("Prepare standby instance"):
            cache = casadm.standby_init(
                cache_dev=cache_device,
                cache_line_size=int(cls.value.value / Unit.KibiByte.value),
                cache_id=cache_id,
                force=True,
            )

        with TestRun.step(f"Populate the passive instance with valid metadata"):
            Dd().input(md_dump.full_path).output(f"/dev/cas-cache-{cache_id}").run()
            sync()

        with TestRun.step(f"Standby detach"):
            cache.standby_detach()

        with TestRun.step(f"Corrupt {block_size} on the offset {offset*block_size}"):
            corrupted_md = prepare_corrupted_md(md_dump, offset, block_size)

        with TestRun.step(f"Copy corrupted metadata to the passive instance"):
            Dd().input(corrupted_md.full_path).output(cache_device.path).run()
            sync()

        with TestRun.step("Try to activate cache instance"):
            output = TestRun.executor.run(
                standby_activate_cmd(cache_dev=cache_device.path, cache_id=str(cache_id))
            )

        with TestRun.step("Per iteration cleanup"):
            cache.stop()
            corrupted_md.remove(force=True, ignore_errors=True)

    with TestRun.step("Test cleanup"):
        md_dump.remove()


def get_offsets_to_corrupt(md_size, bs, count=100):
    offsets = list(range(0, int(md_size.value), bs.value))
    offsets = random.choices(offsets, k=min(len(offsets), count))

    # Offset is expresed as a number of blocks
    return [int(o / bs.value) for o in offsets]


def prepare_md_dump(cache_device, core_device, cls, cache_id):
    with TestRun.step("Setup WB cache instance with one core"):
        cache = casadm.start_cache(
            cache_dev=cache_device,
            cache_line_size=cls,
            cache_mode=CacheMode.WB,
            cache_id=cache_id,
            force=True,
        )
        cache.add_core(core_device)

    with TestRun.step("Get metadata size"):
        dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout
        md_size = dmesg.get_metadata_size(dmesg_out)

    with TestRun.step("Dump the metadata of the cache"):
        dump_file_path = "/tmp/test_activate_corrupted.dump"
        md_dump = File(dump_file_path)
        md_dump.remove(force=True, ignore_errors=True)

        dd_count = int(md_size / Size(1, Unit.MebiByte)) + 1
        (
            Dd()
            .input(cache_device.path)
            .output(md_dump.full_path)
            .block_size(Size(1, Unit.MebiByte))
            .count(dd_count)
            .run()
        )
        md_dump.refresh_item()

    with TestRun.step("Stop cache device"):
        cache.stop()

        return md_dump


def prepare_corrupted_md(md_dump, offset_to_corrupt, bs):
    invalid_dump_path = "/tmp/test_activate_corrupted.invalid_dump"
    dd_count = offset_to_corrupt + 1

    md_dump.copy(destination=invalid_dump_path, force=True)
    corrupted_md = File(invalid_dump_path)
    (
        Dd()
        .input("/dev/urandom")
        .output(corrupted_md.full_path)
        .block_size(bs)
        .count(dd_count)
        .seek(offset_to_corrupt)
        .conv("notrunc")
        .run()
    )
    corrupted_md.refresh_item()

    return corrupted_md
