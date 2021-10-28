#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import re

from api.cas import casadm
from core.test_run import TestRun
from test_utils import os_utils
from test_utils.size import Size, Unit
from test_tools.fio.fio import Fio
from test_tools.blktrace import BlkTrace, BlkTraceMask
from test_tools.fio.fio_param import ReadWrite, IoEngine
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_trim_start_discard():
    """
    title: Check discarding cache device at cache start
    description: |
       Create 2 partitions on trim-supporting device, write pattern to both partitions,
       start blktrace against first one, start cache on first partition and check if discard
       requests were sent at all and only to the first partition.
    pass_criteria:
      - Partition used for cache is discarded.
      - Second partition is untouched - written pattern is preserved.
    """
    with TestRun.step("Clearing dmesg"):
        TestRun.executor.run_expect_success("dmesg -C")

    with TestRun.step("Preparing cache device"):
        dev = TestRun.disks['cache']
        dev.create_partitions([Size(500, Unit.MebiByte), Size(500, Unit.MebiByte)])
        cas_part = dev.partitions[0]
        non_cas_part = dev.partitions[1]

    with TestRun.step("Writing different pattern on partitions"):
        cas_fio = write_pattern(cas_part.path)
        non_cas_fio = write_pattern(non_cas_part.path)
        cas_fio.run()
        non_cas_fio.run()

    # TODO add blktracing for non-cas part
    with TestRun.step("Starting blktrace against first (cache) partition"):
        blktrace = BlkTrace(cas_part, BlkTraceMask.discard)
        blktrace.start_monitoring()

    with TestRun.step("Starting cache"):
        cache = casadm.start_cache(cas_part, force=True)
        metadata_size = get_metadata_size_from_dmesg()

    with TestRun.step("Stop blktrace and check if discard requests were issued"):
        cache_reqs = blktrace.stop_monitoring()
        cache_part_start = cas_part.begin

        # CAS should discard cache device during cache start
        if len(cache_reqs) == 0:
            TestRun.fail("No discard requests issued to the cas partition!")

        non_meta_sector = (cache_part_start + metadata_size).get_value(Unit.Blocks512)
        non_meta_size = (cas_part.size - metadata_size).get_value(Unit.Byte)
        for req in cache_reqs:
            if req.sector_number != non_meta_sector:
                TestRun.fail(f"Discard request issued to wrong sector: {req.sector_number}, "
                             f"expected: {non_meta_sector}")
            if req.byte_count != non_meta_size:
                TestRun.fail(f"Discard request issued with wrong bytes count: {req.byte_count}, "
                             f"expected: {non_meta_size} bytes")

        cas_fio.read_write(ReadWrite.read)
        non_cas_fio.read_write(ReadWrite.read)
        cas_fio.verification_with_pattern("0x00")
        cas_fio.offset(metadata_size)
        cas_fio.run()
        non_cas_fio.run()

    with TestRun.step("Stopping cache"):
        cache.stop()


def write_pattern(device):
    return (Fio().create_command()
                 .io_engine(IoEngine.libaio)
                 .read_write(ReadWrite.write)
                 .target(device)
                 .direct()
                 .verification_with_pattern()
            )


def get_metadata_size_from_dmesg():
    dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout
    for s in dmesg_out.split("\n"):
        if "Hash offset" in s:
            offset = re.search("[0-9]* kiB", s).group()
            offset = Size(int(re.search("[0-9]*", offset).group()), Unit.KibiByte)
        if "Hash size" in s:
            size = re.search("[0-9]* kiB", s).group()
            size = Size(int(re.search("[0-9]*", size).group()), Unit.KibiByte)

    # Metadata is 128KiB aligned
    return (offset + size).align_up(128 * Unit.KibiByte.value)
