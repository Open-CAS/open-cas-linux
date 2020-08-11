#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import time
from collections import namedtuple
import random

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskTypeLowerThan, DiskType
from test_tools.blktrace import BlkTrace, BlkTraceMask, ActionKind, RwbsKind
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
def test_acp_functional(cache_mode):
    """
        title: Validate ACP behavior.
        description: |
          Validate that ACP is cleaning dirty data from chunks bucket - sorted by number of
          dirty pages.
        pass_criteria:
          - All chunks are cleaned in proper order
    """
    chunks_count = 8
    chunk_size = Size(100, Unit.MebiByte)
    chunk_list = []

    def sector_in_chunk(chunk, blktrace_header):
        sector_to_size = Size(blktrace_header.sector_number, Unit.Blocks512)
        return chunk.offset <= sector_to_size < chunk.offset + chunk_size

    def get_header_chunk(bucket_chunks, blktrace_header):
        return next((c for c in bucket_chunks if sector_in_chunk(c, blktrace_header)), None)

    def sector_in_tested_region(blktrace_header, list_of_chunks):
        return any([sector_in_chunk(c, blktrace_header) for c in list_of_chunks])

    with TestRun.step("Prepare devices."):
        cache_device = TestRun.disks['cache']
        core_device = TestRun.disks['core']
        cache_device.create_partitions([chunk_size * chunks_count])
        cache_device = cache_device.partitions[0]

    with TestRun.step("Start cache in WB mode, set cleaning policy to NOP "
                      "and add whole disk as core."):
        cache = casadm.start_cache(cache_device, cache_mode)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        core = cache.add_core(core_device)

    with TestRun.step("Run separate random writes with random amount of data on every "
                      "100 MiB part of CAS device."):
        Chunk = namedtuple('Chunk', 'offset writes_size')
        random_chunk_writes = random.sample(range(1, 101), chunks_count)
        for i in range(chunks_count):
            c = Chunk(chunk_size * i, Size(random_chunk_writes[i], Unit.MebiByte))
            chunk_list.append(c)

        fio = (Fio()
               .create_command()
               .io_engine(IoEngine.sync)
               .read_write(ReadWrite.randwrite)
               .direct()
               .size(chunk_size)
               .block_size(Size(1, Unit.Blocks4096))
               .target(f"{core.system_path}"))
        for chunk in chunk_list:
            fio.add_job().offset(chunk.offset).io_size(chunk.writes_size)
        fio.run()

        dirty_blocks = cache.get_dirty_blocks()
        if dirty_blocks == Size.zero():
            TestRun.fail("No dirty data on cache after IO.")
        TestRun.LOGGER.info(str(cache.get_statistics()))

    with TestRun.step("Switch cleaning policy to ACP and start blktrace monitoring."):
        trace = BlkTrace(core.core_device, BlkTraceMask.write)
        trace.start_monitoring()

        initial_dirty_blocks = cache.get_dirty_blocks()
        cache.set_cleaning_policy(CleaningPolicy.acp)
        while cache.get_dirty_blocks() > Size.zero():
            time.sleep(10)
            if cache.get_dirty_blocks() == initial_dirty_blocks:
                TestRun.fail(f"No data flushed in 10s.\n{str(cache.get_statistics())}")
            initial_dirty_blocks = cache.get_dirty_blocks()

        TestRun.LOGGER.info(str(cache.get_statistics()))

        action_kind = ActionKind.IoHandled
        output = trace.stop_monitoring()
        blktrace_output = [h for h in output if h.action == action_kind
                           and RwbsKind.F not in h.rwbs]

        if not blktrace_output:
            TestRun.fail(f"No {action_kind.name} entries in blktrace output!")
        TestRun.LOGGER.debug(f"Blktrace headers count: {len(blktrace_output)}.")

    with TestRun.step("Using blktrace verify that cleaning thread cleans data from "
                      "all CAS device parts in proper order."):
        all_writes_ok = True
        last_sector = None
        max_percent = 100
        bucket_chunks = []
        current_chunk = None

        for header in blktrace_output:
            # Sector not in current chunk - search for the next chunk
            if current_chunk is None or \
                    not sector_in_chunk(current_chunk, header):
                # Search for bucket with chunks that contain most dirty data
                while not bucket_chunks and max_percent > 0:
                    bucket_chunks = [chunk for chunk in chunk_list
                                     if max_percent >= chunk.writes_size.get_value(Unit.MebiByte)
                                     > max_percent - 10]
                    max_percent -= 10

                if not bucket_chunks:
                    TestRun.fail(f"No chunks left for sector {header.sector_number} "
                                 f"({Size(header.sector_number, Unit.Blocks512)}).")

                # Get chunk within current bucket where current header sector is expected
                chunk = get_header_chunk(bucket_chunks, header)
                if not chunk:
                    TestRun.LOGGER.error(f"Sector {header.sector_number} "
                                         f"({Size(header.sector_number, Unit.Blocks512)}) "
                                         f"not in current bucket.")
                    all_writes_ok = False
                    if not sector_in_tested_region(header, chunk_list):
                        TestRun.LOGGER.error(f"Sector {header.sector_number} "
                                             f"({Size(header.sector_number, Unit.Blocks512)}) "
                                             f"outside of any tested chunk.")
                    continue

                # Set new chunk as current
                if current_chunk:
                    TestRun.LOGGER.info(f"Writes to chunk: {write_counter}")
                current_chunk = chunk
                write_counter = 1
                bucket_chunks.remove(chunk)
                last_sector = header.sector_number
                TestRun.LOGGER.debug(f"First written sector in new chunk: {header.sector_number} "
                                     f"({Size(header.sector_number, Unit.Blocks512)})")
                continue

            # Sector in current chunk - check sequential order
            if last_sector is None or header.sector_number >= last_sector:
                last_sector = header.sector_number
            else:
                TestRun.LOGGER.error(f"Sectors in chunk <{current_chunk.offset}, "
                                     f"{str(current_chunk.offset + chunk_size)}) written in bad "
                                     f"order - sector {header.sector_number} ("
                                     f"{Size(header.sector_number, Unit.Blocks512)}) after sector "
                                     f"{last_sector} ({Size(last_sector, Unit.Blocks512)})")
                all_writes_ok = False
            write_counter += 1
        TestRun.LOGGER.info(f"Writes to chunk: {write_counter}")

        if all_writes_ok:
            TestRun.LOGGER.info("All sectors written in proper order.")
