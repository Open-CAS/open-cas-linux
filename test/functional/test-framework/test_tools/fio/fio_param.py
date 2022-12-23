#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import datetime
import json
import secrets
from enum import Enum
from types import SimpleNamespace as Namespace

from connection.base_executor import BaseExecutor
from core.test_run import TestRun
from storage_devices.device import Device
from test_tools.fio.fio_result import FioResult
from test_utils.linux_command import LinuxCommand
from test_utils.size import Size


class CpusAllowedPolicy(Enum):
    shared = 0,
    split = 1


class ErrorFilter(Enum):
    none = 0,
    read = 1,
    write = 2,
    io = 3,
    verify = 4,
    all = 5


class FioOutput(Enum):
    normal = 'normal'
    terse = 'terse'
    json = 'json'
    jsonplus = 'json+'


class IoEngine(Enum):
    # Basic read or write I/O. fseek is used to position the I/O location.
    sync = 0,
    # Linux native asynchronous I/O.
    libaio = 1,
    # Basic pread or pwrite I/O.
    psync = 2,
    # Basic readv or writev I/O.
    # Will emulate queuing by coalescing adjacent IOs into a single submission.
    vsync = 3,
    # Basic preadv or pwritev I/O.
    pvsync = 4,
    # POSIX asynchronous I/O using aio_read and aio_write.
    posixaio = 5,
    # File is memory mapped with mmap and data copied using memcpy.
    mmap = 6,
    # RADOS Block Device
    rbd = 7,
    # SPDK Block Device
    spdk_bdev = 8


class ReadWrite(Enum):
    randread = 0,
    randrw = 1,
    randwrite = 2,
    read = 3,
    readwrite = 4,
    write = 5,
    trim = 6,
    randtrim = 7,
    trimwrite = 8


class VerifyMethod(Enum):
    # Use an md5 sum of the data area and store it in the header of each block.
    md5 = 0,
    # Use an experimental crc64 sum of the data area and store it in the header of each block.
    crc64 = 1,
    # Use optimized sha1 as the checksum function.
    sha1 = 2,
    # Verify a strict pattern.
    # Normally fio includes a header with some basic information and a checksum, but if this
    # option is set, only the specific pattern set with verify_pattern is verified.
    pattern = 3,
    # Write extra information about each I/O (timestamp, block number, etc.).
    # The block number is verified.
    meta = 4


class RandomGenerator(Enum):
    tausworthe = 0,
    lfsr = 1,
    tausworthe64 = 2


class FioParam(LinuxCommand):
    def __init__(self, fio, command_executor: BaseExecutor, command_name):
        LinuxCommand.__init__(self, command_executor, command_name)
        self.verification_pattern = ''
        self.fio = fio

    def get_verification_pattern(self):
        if not self.verification_pattern:
            self.verification_pattern = f'0x{secrets.token_hex(32)}'
        return self.verification_pattern

    def allow_mounted_write(self, value: bool = True):
        return self.set_param('allow_mounted_write', int(value))

    # example: "bs=8k,32k" => 8k for reads, 32k for writes and trims
    def block_size(self, *sizes: Size):
        return self.set_param('blocksize', *[int(size) for size in sizes])

    def blocksize_range(self, ranges):
        value = []
        for bs_range in ranges:
            str_range = str(int(bs_range[0])) + '-' + str(int(bs_range[1]))
            value.append(str_range)
        return self.set_param('blocksize_range', ",".join(value))

    def bs_split(self, value):
        return self.set_param('bssplit', value)

    def buffer_pattern(self, pattern):
        return self.set_param('buffer_pattern', pattern)

    def continue_on_error(self, value: ErrorFilter):
        return self.set_param('continue_on_error', value.name)

    def cpus_allowed(self, value):
        return self.set_param('cpus_allowed', ",".join(value))

    def cpus_allowed_policy(self, value: CpusAllowedPolicy):
        return self.set_param('cpus_allowed_policy', value.name)

    def direct(self, value: bool = True):
        if 'buffered' in self.command_param:
            self.remove_param('buffered')
        return self.set_param('direct', int(value))

    def directory(self, directory):
        return self.set_param('directory', directory)

    def do_verify(self, value: bool = True):
        return self.set_param('do_verify', int(value))

    def exit_all_on_error(self, value: bool = True):
        return self.set_flags('exitall_on_error') if value \
            else self.remove_flag('exitall_on_error')

    def group_reporting(self, value: bool = True):
        return self.set_flags('group_reporting') if value else self.remove_flag('group_reporting')

    def file_name(self, path):
        return self.set_param('filename', path)

    def file_size(self, size: Size):
        return self.set_param('filesize', int(size))

    def file_size_range(self, ranges):
        value = []
        for bs_range in ranges:
            str_range = str(int(bs_range[0])) + '-' + str(int(bs_range[1]))
            value.append(str_range)
        return self.set_param('filesize', ",".join(value))

    def fsync(self, value: int):
        return self.set_param('fsync', value)

    def ignore_errors(self, read_errors, write_errors, verify_errors):
        separator = ':'
        return self.set_param(
            'ignore_error',
            separator.join(str(err) for err in read_errors),
            separator.join(str(err) for err in write_errors),
            separator.join(str(err) for err in verify_errors))

    def io_depth(self, value: int):
        if value != 1:
            if 'ioengine' in self.command_param and \
                    self.command_param['ioengine'] == 'sync':
                TestRun.LOGGER.warning("Setting iodepth will have no effect with "
                                              "'ioengine=sync' setting")
        return self.set_param('iodepth', value)

    def io_engine(self, value: IoEngine):
        if value == IoEngine.sync:
            if 'iodepth' in self.command_param and self.command_param['iodepth'] != 1:
                TestRun.LOGGER.warning("Setting 'ioengine=sync' will cause iodepth setting "
                                              "to be ignored")
        return self.set_param('ioengine', value.name)

    def io_size(self, value: Size):
        return self.set_param('io_size', int(value.get_value()))

    def loops(self, value: int):
        return self.set_param('loops', value)

    def no_random_map(self, value: bool = True):
        if 'verify' in self.command_param:
            raise ValueError("'NoRandomMap' parameter is mutually exclusive with verify")
        if value:
            return self.set_flags('norandommap')
        else:
            return self.remove_flag('norandommap')

    def nr_files(self, value: int):
        return self.set_param('nrfiles', value)

    def num_ios(self, value: int):
        return self.set_param('number_ios', value)

    def num_jobs(self, value: int):
        return self.set_param('numjobs', value)

    def offset(self, value: Size):
        return self.set_param('offset', int(value.get_value()))

    def offset_increment(self, value: Size):
        return self.set_param('offset_increment', f"{value.value}{value.unit.get_short_name()}")

    def percentage_random(self, value: int):
        if value <= 100:
            return self.set_param('percentage_random', value)
        raise ValueError("Argument out of range. Should be 0-100.")

    def pool(self, value):
        return self.set_param('pool', value)

    def ramp_time(self, value: datetime.timedelta):
        return self.set_param('ramp_time', int(value.total_seconds()))

    def random_distribution(self, value):
        return self.set_param('random_distribution', value)

    def rand_repeat(self, value: int):
        return self.set_param('randrepeat', value)

    def rand_seed(self, value: int):
        return self.set_param('randseed', value)

    def read_write(self, rw: ReadWrite):
        return self.set_param('readwrite', rw.name)

    def run_time(self, value: datetime.timedelta):
        if value.total_seconds() == 0:
            raise ValueError("Runtime parameter must not be set to 0.")
        return self.set_param('runtime', int(value.total_seconds()))

    def serialize_overlap(self, value: bool = True):
        return self.set_param('serialize_overlap', int(value))

    def size(self, value: Size):
        return self.set_param('size', int(value.get_value()))

    def stonewall(self, value: bool = True):
        return self.set_flags('stonewall') if value else self.remove_param('stonewall')

    def sync(self, value: bool = True):
        return self.set_param('sync', int(value))

    def time_based(self, value: bool = True):
        return self.set_flags('time_based') if value else self.remove_flag('time_based')

    def thread(self, value: bool = True):
        return self.set_flags('thread') if value else self.remove_param('thread')

    def lat_percentiles(self, value: bool):
        return self.set_param('lat_percentiles', int(value))

    def scramble_buffers(self, value: bool):
        return self.set_param('scramble_buffers', int(value))

    def slat_percentiles(self, value: bool):
        return self.set_param('slat_percentiles', int(value))

    def spdk_core_mask(self, value: str):
        return self.set_param('spdk_core_mask', value)

    def spdk_json_conf(self, path):
        return self.set_param('spdk_json_conf', path)

    def clat_percentiles(self, value: bool):
        return self.set_param('clat_percentiles', int(value))

    def percentile_list(self, value: []):
        val = ':'.join(value) if len(value) > 0 else '100'
        return self.set_param('percentile_list', val)

    def verification_with_pattern(self, pattern=None):
        if pattern is not None and pattern != '':
            self.verification_pattern = pattern
        return self.verify(VerifyMethod.pattern) \
            .set_param('verify_pattern', self.get_verification_pattern()) \
            .do_verify()

    def verify(self, value: VerifyMethod):
        return self.set_param('verify', value.name)

    def create_only(self, value: bool = False):
        return self.set_param('create_only', int(value))

    def verify_pattern(self, pattern=None):
        return self.set_param('verify_pattern', pattern or self.get_verification_pattern())

    def verify_backlog(self, value: int):
        return self.set_param('verify_backlog', value)

    def verify_dump(self, value: bool = True):
        return self.set_param('verify_dump', int(value))

    def verify_fatal(self, value: bool = True):
        return self.set_param('verify_fatal', int(value))

    def verify_only(self, value: bool = True):
        return self.set_flags('verify_only') if value else self.remove_param('verify_only')

    def write_hint(self, value: str):
        return self.set_param('write_hint', value)

    def write_percentage(self, value: int):
        if value <= 100:
            return self.set_param('rwmixwrite', value)
        raise ValueError("Argument out of range. Should be 0-100.")

    def random_generator(self, value: RandomGenerator):
        return self.set_param('random_generator', value.name)

    def target(self, target):
        if isinstance(target, Device):
            return self.file_name(target.path)
        return self.file_name(target)

    def add_job(self, job_name=None):
        if not job_name:
            job_name = f'job{len(self.fio.jobs)}'
        new_job = FioParamConfig(self.fio, self.command_executor, f'[{job_name}]')
        self.fio.jobs.append(new_job)
        return new_job

    def clear_jobs(self):
        self.fio.jobs = []

        return self

    def edit_global(self):
        return self.fio.global_cmd_parameters

    def run(self, fio_timeout: datetime.timedelta = None):
        if "per_job_logs" in self.fio.global_cmd_parameters.command_param:
            self.fio.global_cmd_parameters.set_param("per_job_logs", '0')
        fio_output = self.fio.run(fio_timeout)
        if fio_output.exit_code != 0:
            raise Exception(f"Exception occurred while trying to execute fio, exit_code:"
                            f"{fio_output.exit_code}.\n"
                            f"stdout: {fio_output.stdout}\nstderr: {fio_output.stderr}")
        TestRun.executor.run(f"sed -i '/^[[:alnum:]]/d' {self.fio.fio_file}")  # Remove warnings
        out = self.command_executor.run_expect_success(f"cat {self.fio.fio_file}").stdout
        return self.get_results(out)

    def run_in_background(self):
        if "per_job_logs" in self.fio.global_cmd_parameters.command_param:
            self.fio.global_cmd_parameters.set_param("per_job_logs", '0')
        return self.fio.run_in_background()

    @staticmethod
    def get_results(result):
        data = json.loads(result, object_hook=lambda d: Namespace(**d))
        jobs_list = []
        if hasattr(data, 'jobs'):
            jobs = data.jobs
            for job in jobs:
                job_result = FioResult(data, job)
                jobs_list.append(job_result)
        return jobs_list


class FioParamCmd(FioParam):
    def __init__(self, fio, command_executor: BaseExecutor, command_name='fio'):
        FioParam.__init__(self, fio, command_executor, command_name)
        self.param_name_prefix = "--"


class FioParamConfig(FioParam):
    def __init__(self, fio, command_executor: BaseExecutor, command_name='[global]'):
        FioParam.__init__(self, fio, command_executor, command_name)
        self.param_name_prefix = "\n"
