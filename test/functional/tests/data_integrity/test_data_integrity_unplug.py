#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import re
from bisect import bisect_right
from datetime import timedelta
from time import sleep

import pytest

from api.cas import casadm, cli_messages
from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from storage_devices.ramdisk import RamDisk
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite
from test_utils.asynchronous import start_async_func
from test_utils.filesystem.directory import Directory
from test_utils.output import CmdException
from test_utils.size import Unit, Size

ram_disk, tmp_dir, fio_seed = None, None, None
num_jobs = 8
job_workset_size = Size(1, Unit.MiB)
block_size = Size(1, Unit.Blocks4096)
job_workset_blocks = int(job_workset_size / block_size)

total_workset_blocks = num_jobs * job_workset_blocks

# g_io_log[b, j] is a list of I/O operations that hit sector b in job j workset.
# IOs on the list are identified by its sequential number (seqno) within the job j.
# g_io_log [b, j] is sorted by ascending I/O number.
# Value of -1 indicated prefill (meaning no known I/O hit sector b within job
# j within the analyzed interval)
g_io_log = [[[-1] for _ in range(job_workset_blocks)] for _ in range(num_jobs)]

# seqno of the last I/O taken into account in g_io_log (same for all jobs)
max_log_seqno = -1


@pytest.mark.os_dependent
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.asyncio
async def test_data_integrity_unplug(cache_mode):
    """
        title: Test if data integrity is maintained in a power failure scenario.
        description: |
          The test checks if the data written to the cache device is saved correctly in a power
          failure scenario, which is simulated by unplugging the cache device.
          FIO is interrupted when the cache device is unplugged. The test determines how many
          writes each FIO job was able to perform before the unplug and then checks if the data
          on the cache device matches FIO output up to the unplug (bearing in mind that the last
          write might have been interrupted).
        pass_criteria:
          - No system crash.
          - Data on the cache device are consistent with the data sent from FIO.
    """
    global fio_seed, tmp_dir, ram_disk
    cache_dev = TestRun.disks["cache"]
    core_dev = TestRun.disks["core"]

    sleep_max_s = timedelta(seconds=10)

    with TestRun.step("Test prepare"):
        random.seed(TestRun.random_seed)
        fio_seed = random.randint(0, 2 ** 32)
        TestRun.LOGGER.info(f"FIO seed: {fio_seed}")
        tmp_dir = Directory.create_temp_directory()
        TestRun.LOGGER.info(f"Temporary directory: {tmp_dir.full_path}")
        ram_disk = RamDisk.create(Size(1, Unit.GiB), 1)[0]

        # csums[j][i] is csum for i-th io of j-th job
        csums = [{} for _ in range(num_jobs)]

    with TestRun.step("Test iterations:"):
        for cache_line_size in TestRun.iteration(CacheLineSize):
            with TestRun.step("Prefill the core device."):
                write_device(core_dev.path)
                data_prefill_cs = read_device_md5s(core_dev.path)

            # csums_rev is a reverse mapping to identify job, sector and seqno of I/O
            # with given csum
            csums_rev = {}
            for j in range(num_jobs):
                for b in range(job_workset_blocks):
                    cs = data_prefill_cs[j][b]
                    csums_rev[cs] = get_data_name(j, b, -1)

            with TestRun.step("Start a cache, add a core and set cache cleaning policy to NOP"):
                cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
                exported_object = cache.add_core(core_dev)
                cache.set_cleaning_policy(CleaningPolicy.nop)

            with TestRun.step("Start FIO to the exported object"):
                fio = prepare_base_fio() \
                    .target(exported_object.path) \
                    .run_time(100 * sleep_max_s)
                for i in range(num_jobs):
                    fio.add_job(f"di_{i}") \
                       .offset(job_workset_size * i) \
                       .io_size(Size(100, Unit.GiB))

                fio_task = start_async_func(fio.fio.run)

            with TestRun.step("Hot unplug the cache device after random time"):
                wait_time_s = random.randint(5, int(sleep_max_s.total_seconds()))
                sleep(wait_time_s)
                cache_dev.unplug()

            with TestRun.step("Analyze FIO execution after hot unplug"):
                fio_output = fio_task.result()
                if fio_output.exit_code == 0:
                    TestRun.LOGGER.warning(
                        "Unexpectedly successful fio - check if the device was unplugged correctly."
                    )
                results = fio.get_results(TestRun.executor.run(f"cat {fio.fio.fio_file}").stdout)
                ios = [r.job.write.total_ios for r in results]

            with TestRun.step("Stop cache without flushing data"):
                try:
                    cache.stop(no_data_flush=True)
                except CmdException as e:
                    if not cli_messages.check_stderr_msg(e.output, cli_messages.stop_cache_errors):
                        raise

            with TestRun.step("Plug back the cache device"):
                cache_dev.plug()

            with TestRun.step("Load cache"):
                cache = casadm.load_cache(cache_dev)

            with TestRun.step("Check data"):
                csums_actual = read_device_md5s(exported_object.path)

                # The last I/O in each job is interrupted by the unplug. It could have made it
                # to the medium or not. So the last I/O we expect to actually hit the disk
                # is 'num_io-2' or 'num_io-1' for each job. Below 'n1_' refers to 'num_io-1'
                # and 'n2_' refers to 'num_io-2'

                # seqno[j] is the last I/O seqno for given job (entire workset)
                n2_seqno = [io - 2 for io in ios]
                n1_seqno = [io - 1 for io in ios]

                # pattern[j][b] is the last I/O seqno for job j block b
                n2_pattern = get_pattern(n2_seqno)
                n1_pattern = get_pattern(n1_seqno)

                # Make sure we know data checksums for I/O that we expect to have
                # been committed assuming either n2_seqno or n1_seqno is the last
                # I/O committed by each job.
                gen_csums(ram_disk.path, n1_seqno, n1_pattern, csums, csums_rev)
                gen_csums(ram_disk.path, n2_seqno, n2_pattern, csums, csums_rev)

                fail = False
                for j in range(num_jobs):
                    for b in range(job_workset_blocks):
                        # possible checksums assuming n2_pattern or n1_pattern
                        cs_n2 = get_data_csum(j, b, n2_pattern, data_prefill_cs, csums)
                        cs_n1 = get_data_csum(j, b, n1_pattern, data_prefill_cs, csums)

                        # actual checksum read from CAS
                        cs_actual = csums_actual[j][b]

                        if cs_actual != cs_n2 and cs_actual != cs_n1:
                            fail = True

                            # attempt to identify erroneous data by comparing its checksum
                            # against the known checksums
                            identity = csums_rev[cs_actual] if cs_actual in csums_rev else \
                                f"UNKNOWN ({cs_actual[:8]})"

                            TestRun.LOGGER.error(
                                f"MISMATCH job {j} block {b} contains {identity} "
                                f"expected {get_data_name(j, b, n2_pattern[j][b])} "
                                f"or {get_data_name(j, b, n1_pattern[j][b]) }"
                            )

                if fail:
                    break

                cache.stop(no_data_flush=True)


def get_data_name(job, block, io):
    return f"JOB_{job}_SECTOR_{block}_PREFILL" if io == -1 \
        else f"JOB_{job}_SECTOR_{block}_IO_{io}"


def write_device(path):
    command = (
        f"dd if=/dev/urandom bs={int(block_size.value)} count={job_workset_blocks} of={path} "
        "oflag=direct"
    )
    TestRun.executor.run_expect_success(command)


# retval[j][b] is the seqno of last I/O to hit block b within job j workset
# assuming last_io_seqno[j] is the seqno of last I/O committed by job j
def get_pattern(last_io_seqno):
    if max(last_io_seqno) > max_log_seqno:
        # collect IO log for 20% steps more than requested maximum to have some headroom
        gen_log(int(max(last_io_seqno) * 1.2))

    # extract only the relevant (last committed) seqno for each block from the io log
    return [[g_io_log[j][b][bisect_right(g_io_log[j][b], last_io_seqno[j]) - 1] for b in
             range(job_workset_blocks)] for j in range(num_jobs)]


# update g_io_log[j,b] information with I/O seqno list up to seqno_max
# for each job j and block b
def gen_log(seqno_max):
    global max_log_seqno
    global g_io_log

    io_log_path = generate_temporary_file_name(tmp_dir, "iolog").stdout
    num_io = [seqno_max + 1] * num_jobs

    fio = prepare_base_fio().target(ram_disk.path)
    for i, io in enumerate(num_io):
        fio.add_job(f"di_{i}") \
            .offset(job_workset_size * i) \
            .io_size(io * block_size) \
            .set_param("write_iolog", f"{io_log_path}_{i}")
    fio.run()

    r = re.compile(r"\S+\s+(read|write)\s+(\d+)\s+(\d+)")
    for j in range(num_jobs):
        log = f"{io_log_path}_{j}"
        nr = 0
        for line in TestRun.executor.run(f"cat {log}").stdout.splitlines():
            m = r.match(line)
            if m:
                if nr > max_log_seqno:
                    block = int(m.group(2)) // block_size.value - j * job_workset_blocks
                    g_io_log[j][block] += [nr]
                nr += 1
            if nr > seqno_max + 1:
                TestRun.fail("Error during pattern generation")
    max_log_seqno = seqno_max


def generate_temporary_file_name(dir_path, prefix="file"):
    return TestRun.executor.run_expect_success(
        f"mktemp --tmpdir={dir_path} -t {prefix}_XXXXXXXX -u"
    )


# update csums and csums_rev with checksum information for
# the case of seqno[b] being the last I/O committed by job b
def gen_csums(dev_path, seqno, pattern, csums, csums_rev):
    if all([all([pattern[j][b] in csums[j] for b in range(job_workset_blocks)]) for j in range(
            num_jobs)]):
        return

    num_io = [sn + 1 for sn in seqno]
    fio = prepare_base_fio().target(ram_disk.path)
    for i, io in enumerate(num_io):
        fio.add_job(f"di_{i}") \
            .offset(job_workset_size * i) \
            .io_size(io * block_size)
    fio.run()

    cs = read_device_md5s(dev_path)

    for j in range(num_jobs):
        for b in range(job_workset_blocks):
            if pattern[j][b] != -1 and not pattern[j][b] in csums[j]:
                csums[j][pattern[j][b]] = cs[j][b]
                csums_rev[cs[j][b]] = get_data_name(j, b, pattern[j][b])


def prepare_base_fio():
    return Fio().create_command() \
        .remove_flag('group_reporting') \
        .read_write(ReadWrite.randwrite) \
        .no_random_map() \
        .direct() \
        .block_size(block_size) \
        .size(job_workset_size) \
        .rand_seed(fio_seed) \
        .set_param("allrandrepeat", 1) \
        .set_flags("refill_buffers")


def read_device_md5s(path):
    result = TestRun.executor.run_expect_success(
        f"for i in 0 `seq {total_workset_blocks - 1}`; do dd if={path} bs={block_size.value} "
        "count=1 skip=$i iflag=direct 2> /dev/null | md5sum; done | cut -d ' ' -f 1"
    ).stdout.splitlines()
    return split_per_job(result)


def split_per_job(v):
    return [v[i:i + job_workset_blocks] for i in range(0, total_workset_blocks, job_workset_blocks)]


def fill_data(dev, max_seqno):
    num_io = [max_seqno + 1] * num_jobs
    fio = prepare_base_fio().target(dev.path)
    for i in range(len(num_io)):
        if num_io[i] == 0:
            continue
        fio.add_job(f"di_{i}") \
            .offset(job_workset_size * i) \
            .io_size(num_io[i] * block_size)
    fio.run()


def get_data_csum(job, block, pattern, data_prefill_cs, csums):
    io = pattern[job][block]
    if io == -1:
        return data_prefill_cs[job][block]
    else:
        return csums[job][io]
