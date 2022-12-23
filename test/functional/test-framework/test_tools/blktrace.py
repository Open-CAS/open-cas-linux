#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import math

from aenum import IntFlag, Enum

from datetime import timedelta

from core.test_run import TestRun
from storage_devices.device import Device
from test_utils.filesystem.directory import Directory
from test_utils.os_utils import is_mounted, drop_caches, DropCachesMode
from test_utils.size import Size, Unit

DEBUGFS_MOUNT_POINT = "/sys/kernel/debug"
PREFIX = "trace_"
HEADER_FORMAT = "%a|%C|%d|%e|%n|%N|%S|%5T.%9t\\n"


class BlkTraceMask(IntFlag):
    read = 1
    write = 1 << 1
    flush = 1 << 2
    sync = 1 << 3
    queue = 1 << 4
    requeue = 1 << 5
    issue = 1 << 6
    complete = 1 << 7
    fs = 1 << 8
    pc = 1 << 9
    notify = 1 << 10
    ahead = 1 << 11
    meta = 1 << 12
    discard = 1 << 13
    drv_data = 1 << 14
    fua = 1 << 15


class ActionKind(Enum):
    IoDeviceRemap = "A"
    IoBounce = "B"
    IoCompletion = "C"
    IoToDriver = "D"
    IoFrontMerge = "F"
    GetRequest = "G"
    IoInsert = "I"
    IoMerge = "M"
    PlugRequest = "P"
    IoHandled = "Q"
    RequeueRequest = "R"
    SleepRequest = "S"
    TimeoutUnplug = "T"     # old version of TimerUnplug
    UnplugRequest = "U"
    TimerUnplug = "UT"
    Split = "X"


class RwbsKind(IntFlag):
    Undefined = 0
    R = 1       # Read
    W = 1 << 1  # Write
    D = 1 << 2  # Discard
    F = 1 << 3  # Flush
    S = 1 << 4  # Synchronous
    M = 1 << 5  # Metadata
    A = 1 << 6  # Read Ahead
    N = 1 << 7  # None of the above

    def __str__(self):
        ret = []
        if self & RwbsKind.R:
            ret.append("read")
        if self & RwbsKind.W:
            ret.append("write")
        if self & RwbsKind.D:
            ret.append("discard")
        if self & RwbsKind.F:
            ret.append("flush")
        if self & RwbsKind.S:
            ret.append("sync")
        if self & RwbsKind.M:
            ret.append("metadata")
        if self & RwbsKind.A:
            ret.append("readahead")
        if self & RwbsKind.N:
            ret.append("none")

        return "|".join(ret)


class BlkTrace:
    def __init__(self, device: Device, *masks: BlkTraceMask):
        self._mount_debugfs()
        if device is None:
            raise Exception("Device not provided")
        self.device = device
        self.masks = "" if not masks else f' -a {" -a ".join([m.name for m in masks])}'
        self.blktrace_pid = -1
        self.__outputDirectoryPath = None

    @staticmethod
    def _mount_debugfs():
        if not is_mounted(DEBUGFS_MOUNT_POINT):
            TestRun.executor.run_expect_success(f"mount -t debugfs none {DEBUGFS_MOUNT_POINT}")

    def start_monitoring(self, buffer_size: Size = None, number_of_subbuffers: int = None):
        if self.blktrace_pid != -1:
            raise Exception(f"blktrace already running with PID: {self.blktrace_pid}")

        self.__outputDirectoryPath = Directory.create_temp_directory().full_path

        drop_caches(DropCachesMode.ALL)

        number_of_subbuffers = ("" if number_of_subbuffers is None
                                else f" --num-sub-buffers={number_of_subbuffers}")
        buffer_size = ("" if buffer_size is None
                       else f" --buffer-size={buffer_size.get_value(Unit.KibiByte)}")
        command = (f"blktrace{number_of_subbuffers}{buffer_size} --dev={self.device.path}"
                   f"{self.masks} --output={PREFIX} --output-dir={self.__outputDirectoryPath}")
        echo_output = TestRun.executor.run_expect_success(
            f"nohup {command} </dev/null &>{self.__outputDirectoryPath}/out & echo $!"
        )
        self.blktrace_pid = int(echo_output.stdout)
        TestRun.LOGGER.info(f"blktrace monitoring for device {self.device.path} started"
                            f" (PID: {self.blktrace_pid}, output dir: {self.__outputDirectoryPath}")

    def stop_monitoring(self):
        if self.blktrace_pid == -1:
            raise Exception("PID for blktrace is not set - has monitoring been started?")

        drop_caches(DropCachesMode.ALL)

        TestRun.executor.run_expect_success(f"kill -s SIGINT {self.blktrace_pid}")
        self.blktrace_pid = -1

        # dummy command for swallowing output of killed command
        TestRun.executor.run("sleep 2 && echo dummy")
        TestRun.LOGGER.info(f"blktrace monitoring for device {self.device.path} stopped")

        return self.__parse_blktrace_output()

    def __parse_blktrace_output(self):
        TestRun.LOGGER.info(f"Parsing blktrace headers from {self.__outputDirectoryPath}... "
                            "Be patient")
        command = (f'blkparse --input-dir={self.__outputDirectoryPath} --input={PREFIX} '
                   f'--format="{HEADER_FORMAT}"')
        blkparse_output = TestRun.executor.run_expect_success(
            command, timeout=timedelta(minutes=60)
        )
        parsed_headers = []
        for line in blkparse_output.stdout.splitlines():
            # At the end per-cpu summary is posted - there is no need for it now
            if line.startswith('CPU'):
                break

            header = Header.parse(line)
            if header is None:
                continue
            parsed_headers.append(header)
        TestRun.LOGGER.info(
            f"Parsed {len(parsed_headers)} blktrace headers from {self.__outputDirectoryPath}"
        )
        parsed_headers.sort(key=lambda x: x.timestamp)
        return parsed_headers


class Header:
    def __init__(self):
        self.action = None
        self.block_count = None
        self.byte_count = None
        self.command = None
        self.error_value = None
        self.rwbs = RwbsKind.Undefined
        self.sector_number = None
        self.timestamp = None

    @staticmethod
    def parse(header_line: str):
        # messages/notifies are not formatted according to --format
        # so should be ignored (or parsed using standard format):
        if "m   N" in header_line:
            return None

        header_fields = header_line.split('|')
        if len(header_fields) != 8:
            return None

        timestamp_fields = header_fields[7].split('.')
        timestamp_nano = int(timestamp_fields[-1]) if len(timestamp_fields) == 2 else 0

        header = Header()
        header.action = ActionKind(header_fields[0])
        header.command = header_fields[1]
        if len(header_fields[2]):
            header.rwbs = RwbsKind['|'.join(list(header_fields[2]))]
        header.error_value = int(header_fields[3])
        header.block_count = int(header_fields[4])
        header.byte_count = int(header_fields[5])
        header.sector_number = int(header_fields[6])
        header.timestamp = int(timestamp_fields[0]) * math.pow(10, 9) + timestamp_nano

        return header

    def __str__(self):
        ret = []
        if self.action:
            ret.append(f"action: {self.action.name}")
        if self.block_count:
            ret.append(f"block_count: {self.block_count}")
        if self.byte_count:
            ret.append(f"byte_count: {self.byte_count}")
        if self.command:
            ret.append(f"command: {self.command}")
        if self.error_value:
            ret.append(f"error_value: {self.error_value}")
        if self.rwbs:
            ret.append(f"rwbs: {self.rwbs}")
        if self.sector_number:
            ret.append(f"sector_number: {self.sector_number}")
        if self.timestamp:
            ret.append(f"timestamp: {self.timestamp}")
        return " ".join(ret)
