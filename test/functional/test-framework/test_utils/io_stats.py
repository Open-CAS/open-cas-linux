#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import re

from core.test_run import TestRun
from test_utils.output import CmdException

SYSFS_LINE_FORMAT = r"^(\d+\s+){10,}\d+$"
PROCFS_LINE_FORMAT = r"^\d+\s+\d+\s+\w+\s+" + SYSFS_LINE_FORMAT[1:]


# This class represents block device I/O statistics.
# For more information see:
# https://www.kernel.org/doc/Documentation/admin-guide/iostats.rst
class IoStats:
    def __init__(self):
        self.reads = None               # field 0
        self.reads_merged = None        # field 1
        self.sectors_read = None        # field 2
        self.read_time_ms = None        # field 3
        self.writes = None              # field 4
        self.writes_merged = None       # field 5
        self.sectors_written = None     # field 6
        self.write_time_ms = None       # field 7
        self.ios_in_progress = None     # field 8
        self.io_time_ms = None          # field 9
        self.io_time_weighed_ms = None  # field 10
        # only in kernels 4.18+
        self.discards = None            # field 11
        self.discards_merged = None     # field 12
        self.sectors_discarded = None   # field 13
        self.discard_time_ms = None     # field 14
        # only in kernels 5.5+
        self.flushes = None             # field 15
        self.flush_time_ms = None       # field 16

    def __sub__(self, other):
        if self.reads < other.reads:
            raise Exception("Cannot subtract Reads")
        if self.writes < other.writes:
            raise Exception("Cannot subtract Writes")

        stats = IoStats()
        stats.reads = self.reads - other.reads
        stats.reads_merged = self.reads_merged - other.reads_merged
        stats.sectors_read = self.sectors_read - other.sectors_read
        stats.read_time_ms = self.read_time_ms - other.read_time_ms
        stats.writes = self.writes - other.writes
        stats.writes_merged = self.writes_merged - other.writes_merged
        stats.sectors_written = self.sectors_written - other.sectors_written
        stats.write_time_ms = self.write_time_ms - other.write_time_ms
        stats.ios_in_progress = 0
        stats.io_time_ms = self.io_time_ms - other.io_time_ms
        stats.io_time_weighed_ms = self.io_time_weighed_ms - other.io_time_weighed_ms
        if stats.discards and other.discards:
            stats.discards = self.discards - other.discards
        if stats.discards_merged and other.discards_merged:
            stats.discards_merged = self.discards_merged - other.discards_merged
        if stats.sectors_discarded and other.sectors_discarded:
            stats.sectors_discarded = self.sectors_discarded - other.sectors_discarded
        if stats.discard_time_ms and other.discard_time_ms:
            stats.discard_time_ms = self.discard_time_ms - other.discard_time_ms
        if stats.flushes and other.flushes:
            stats.flushes = self.flushes - other.flushes
        if stats.flush_time_ms and other.flush_time_ms:
            stats.flush_time_ms = self.flush_time_ms - other.flush_time_ms
        return stats

    @staticmethod
    def parse(stats_line: str):
        stats_line = stats_line.strip()

        if re.match(SYSFS_LINE_FORMAT, stats_line):
            fields = stats_line.split()
        elif re.match(PROCFS_LINE_FORMAT, stats_line):
            fields = stats_line.split()[3:]
        else:
            raise Exception(f"Wrong input format for diskstat parser")

        values = [int(f) for f in fields]

        stats = IoStats()
        stats.reads = values[0]
        stats.reads_merged = values[1]
        stats.sectors_read = values[2]
        stats.read_time_ms = values[3]
        stats.writes = values[4]
        stats.writes_merged = values[5]
        stats.sectors_written = values[6]
        stats.write_time_ms = values[7]
        stats.ios_in_progress = values[8]
        stats.io_time_ms = values[9]
        stats.io_time_weighed_ms = values[10]
        if len(values) > 11:
            stats.discards = values[11]
            stats.discards_merged = values[12]
            stats.sectors_discarded = values[13]
            stats.discard_time_ms = values[14]
            if len(values) > 15:
                stats.flushes = values[15]
                stats.flush_time_ms = values[16]
        return stats

    @staticmethod
    def get_io_stats(device_id):
        stats_output = TestRun.executor.run_expect_success(
            f"cat /proc/diskstats | grep '{device_id} '")
        if not stats_output.stdout.strip():
            raise CmdException("Failed to get statistics for device " + device_id, stats_output)
        return IoStats.parse(stats_line=stats_output.stdout.splitlines()[0])
