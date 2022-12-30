#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from core.test_run import TestRun
from storage_devices.device import Device
from test_utils.size import Size, Unit, UnitPerSecond
from test_utils.time import Time
import csv


class IOstatExtended:
    iostat_option = "x"

    def __init__(self, device_statistics: dict):

        # Notes about params:
        # await param is displayed only on flag -s
        # avgrq-sz doesn't appear in newer versions of iostat -x

        self.device_name = device_statistics["Device"]
        # rrqm/s
        self.read_requests_merged_per_sec = float(device_statistics["rrqm/s"])
        # wrqm/s
        self.write_requests_merged_per_sec = float(device_statistics["wrqm/s"])
        # r/s
        self.read_requests_per_sec = float(device_statistics["r/s"])
        # w/s
        self.write_requests_per_sec = float(device_statistics["w/s"])
        # rkB/s
        self.reads_per_sec = Size(float(device_statistics["rkB/s"]), UnitPerSecond(Unit.KiloByte))
        # wkB/s
        self.writes_per_sec = Size(float(device_statistics["wkB/s"]), UnitPerSecond(Unit.KiloByte))
        # avgqu-sz - in newer versions is named aqu-sz
        self.average_queue_length = float(
            device_statistics["aqu-sz"]
            if "aqu-sz" in device_statistics
            else device_statistics.get("avgqu-sz", 0)
        )
        # r_await
        self.read_average_service_time = Time(milliseconds=float(device_statistics["r_await"]))
        # w_await
        self.write_average_service_time = Time(milliseconds=float(device_statistics["w_await"]))
        # iostat's documentation says to not trust 11th field
        # util
        self.utilization = float(device_statistics["%util"])

    def __str__(self):
        return (
            f"\n=========={self.device_name} IO stats: ==========\n"
            f"Read requests merged per second: {self.read_requests_merged_per_sec}\n"
            f"Write requests merged per second: {self.write_requests_merged_per_sec}\n"
            f"Read requests: {self.read_requests_per_sec}\n"
            f"Write requests: {self.write_requests_per_sec}\n"
            f"Reads per second: {self.reads_per_sec}\n"
            f"Writes per second {self.writes_per_sec}\n"
            f"Average queue length {self.average_queue_length}\n"
            f"Read average service time {self.read_average_service_time}\n"
            f"Write average service time: {self.write_average_service_time}\n"
            f"Utilization: {self.utilization}\n"
            f"=================================================\n"
        )

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.read_requests_merged_per_sec == other.read_requests_merged_per_sec
            and self.write_requests_merged_per_sec == other.write_requests_merged_per_sec
            and self.read_requests_per_sec == other.read_requests_per_sec
            and self.write_requests_per_sec == other.write_requests_per_sec
            and self.reads_per_sec == other.reads_per_sec
            and self.writes_per_sec == other.writes_per_sec
            and self.average_queue_length == other.average_queue_length
            and self.read_average_service_time == other.read_average_service_time
            and self.write_average_service_time == other.write_average_service_time
            and self.utilization == other.utilization
        )

    @classmethod
    def get_iostat_list(
        cls,
        devices_list: [Device],
        since_boot: bool = True,
        interval: int = 1,
    ):
        """
        Returns list of IOstat objects containing extended statistics displayed
        in kibibytes/kibibytes per second.
        """
        return _get_iostat_list(cls, devices_list, since_boot, interval)


class IOstatBasic:
    iostat_option = "d"

    def __init__(self, device_statistics):

        self.device_name = device_statistics["Device"]
        # tps
        self.transfers_per_second = float(device_statistics["tps"])
        # kB_read/s
        self.reads_per_second = Size(
            float(device_statistics["kB_read/s"]), UnitPerSecond(Unit.KiloByte)
        )
        # kB_wrtn/s
        self.writes_per_second = Size(
            float(device_statistics["kB_wrtn/s"]), UnitPerSecond(Unit.KiloByte)
        )
        # kB_read
        self.total_reads = Size(float(device_statistics["kB_read"]), Unit.KibiByte)
        # kB_wrtn
        self.total_writes = Size(float(device_statistics["kB_wrtn"]), Unit.KibiByte)

    def __str__(self):
        return (
            f"\n=========={self.device_name} IO stats: ==========\n"
            f"Transfers per second: {self.transfers_per_second}\n"
            f"Kilobytes read per second: {self.reads_per_second}\n"
            f"Kilobytes written per second: {self.writes_per_second}\n"
            f"Kilobytes read: {self.total_reads}\n"
            f"Kilobytes written: {self.total_writes}\n"
            f"=================================================\n"
        )

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if not isinstance(other, IOstatBasic):
            return False
        return vars(self) == vars(other)

    @classmethod
    def get_iostat_list(
        cls,
        devices_list: [Device],
        since_boot: bool = True,
        interval: int = 1,
    ):
        """
        Returns list of IOstat objects containing basic statistics displayed
        in kibibytes/kibibytes per second.
        """
        return _get_iostat_list(cls, devices_list, since_boot, interval)


def _get_iostat_list(
    class_type: type,
    devices_list: [Device],
    since_boot: bool,
    interval: int,
):
    if interval < 1:
        raise ValueError("iostat interval must be positive!")

    iostat_cmd = f"iostat -k -{class_type.iostat_option} "

    if not since_boot:
        iostat_cmd += f"-y {interval} 1 "

    iostat_cmd += " ".join([name.device_id for name in devices_list])

    sed_cmd = "sed -n '/^$/d;s/\s\+/,/g;/^Device/,$p'"

    cmd = f"{iostat_cmd} | {sed_cmd}"

    lines = TestRun.executor.run(cmd).stdout.splitlines()
    table_contents = csv.DictReader(lines, delimiter=",")

    ret = []
    for device in table_contents:
        ret += [class_type(device)]

    return ret
