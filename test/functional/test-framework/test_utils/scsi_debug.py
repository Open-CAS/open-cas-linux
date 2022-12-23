#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from core.test_run import TestRun

syslog_path = "/var/log/messages"


class Logs:
    last_read_line = 1
    FLUSH = re.compile(r"scsi_debug:[\s\S]*cmd 35")
    FUA = re.compile(r"scsi_debug:[\s\S]*cmd 2a 08")

    @staticmethod
    def check_syslog_for_signals():
        Logs.check_syslog_for_flush()
        Logs.check_syslog_for_fua()

    @staticmethod
    def check_syslog_for_flush():
        """Check syslog for FLUSH logs"""
        log_lines = Logs._read_syslog(Logs.last_read_line)
        flush_logs_counter = Logs._count_logs(log_lines, Logs.FLUSH)
        log_type = "FLUSH"
        Logs._validate_logs_amount(flush_logs_counter, log_type)

    @staticmethod
    def check_syslog_for_fua():
        """Check syslog for FUA logs"""
        log_lines = Logs._read_syslog(Logs.last_read_line)
        fua_logs_counter = Logs._count_logs(log_lines, Logs.FUA)
        log_type = "FUA"
        Logs._validate_logs_amount(fua_logs_counter, log_type)

    @staticmethod
    def _read_syslog(last_read_line: int):
        """Read recent lines in syslog, mark last line and return read lines as list."""
        log_lines = TestRun.executor.run_expect_success(
            f"tail -qn +{last_read_line} {syslog_path}"
        ).stdout.splitlines()
        # mark last read line to continue next reading from here
        Logs.last_read_line += len(log_lines)

        return log_lines

    @staticmethod
    def _count_logs(log_lines: list, expected_log):
        """Count specified log in list and return its amount."""
        logs_counter = 0

        for line in log_lines:
            is_log_in_line = expected_log.search(line)
            if is_log_in_line is not None:
                logs_counter += 1

        return logs_counter

    @staticmethod
    def _validate_logs_amount(logs_counter: int, log_type: str):
        """Validate amount of logs and return"""
        if logs_counter == 0:
            if Logs._is_flush(log_type):
                TestRun.LOGGER.error(f"{log_type} log not occured")
            else:
                TestRun.LOGGER.warning(f"{log_type} log not occured")
        elif logs_counter == 1:
            TestRun.LOGGER.warning(f"{log_type} log occured only once.")
        else:
            TestRun.LOGGER.info(f"{log_type} log occured {logs_counter} times.")

    @staticmethod
    def _is_flush(log_type: str):
        return log_type == "FLUSH"
