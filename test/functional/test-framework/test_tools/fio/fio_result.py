#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


from test_utils.size import Size, Unit, UnitPerSecond
from test_utils.time import Time


class FioResult:
    def __init__(self, result, job):
        self.result = result
        self.job = job

    def __str__(self):
        result_dict = {
            "Total read I/O": self.read_io(),
            "Total read bandwidth ": self.read_bandwidth(),
            "Read bandwidth average ": self.read_bandwidth_average(),
            "Read bandwidth deviation ": self.read_bandwidth_deviation(),
            "Read IOPS": self.read_iops(),
            "Read runtime": self.read_runtime(),
            "Read average completion latency": self.read_completion_latency_average(),
            "Total write I/O": self.write_io(),
            "Total write bandwidth ": self.write_bandwidth(),
            "Write bandwidth average ": self.write_bandwidth_average(),
            "Write bandwidth deviation ": self.write_bandwidth_deviation(),
            "Write IOPS": self.write_iops(),
            "Write runtime": self.write_runtime(),
            "Write average completion latency": self.write_completion_latency_average(),
        }

        disks_name = self.disks_name()
        if disks_name:
            result_dict.update({"Disk name": ",".join(disks_name)})

        result_dict.update({"Total number of errors": self.total_errors()})

        s = ""
        for key in result_dict.keys():
            s += f"{key}: {result_dict[key]}\n"
        return s

    def total_errors(self):
        return getattr(self.job, "total_err", 0)

    def disks_name(self):
        disks_name = []
        if hasattr(self.result, "disk_util"):
            for disk in self.result.disk_util:
                disks_name.append(disk.name)
        return disks_name

    def read_io(self):
        return Size(self.job.read.io_kbytes, Unit.KibiByte)

    def read_bandwidth(self):
        return Size(self.job.read.bw, UnitPerSecond(Unit.KibiByte))

    def read_bandwidth_average(self):
        return Size(self.job.read.bw_mean, UnitPerSecond(Unit.KibiByte))

    def read_bandwidth_deviation(self):
        return Size(self.job.read.bw_dev, UnitPerSecond(Unit.KibiByte))

    def read_iops(self):
        return self.job.read.iops

    def read_runtime(self):
        return Time(microseconds=self.job.read.runtime)

    def read_completion_latency_min(self):
        return Time(nanoseconds=self.job.read.lat_ns.min)

    def read_completion_latency_max(self):
        return Time(nanoseconds=self.job.read.lat_ns.max)

    def read_completion_latency_average(self):
        return Time(nanoseconds=self.job.read.lat_ns.mean)

    def read_completion_latency_percentile(self):
        return self.job.read.lat_ns.percentile.__dict__

    def read_requests_number(self):
        return self.result.disk_util[0].read_ios

    def write_io(self):
        return Size(self.job.write.io_kbytes, Unit.KibiByte)

    def write_bandwidth(self):
        return Size(self.job.write.bw, UnitPerSecond(Unit.KibiByte))

    def write_bandwidth_average(self):
        return Size(self.job.write.bw_mean, UnitPerSecond(Unit.KibiByte))

    def write_bandwidth_deviation(self):
        return Size(self.job.write.bw_dev, UnitPerSecond(Unit.KibiByte))

    def write_iops(self):
        return self.job.write.iops

    def write_runtime(self):
        return Time(microseconds=self.job.write.runtime)

    def write_completion_latency_average(self):
        return Time(nanoseconds=self.job.write.lat_ns.mean)

    def write_completion_latency_min(self):
        return Time(nanoseconds=self.job.write.lat_ns.min)

    def write_completion_latency_max(self):
        return Time(nanoseconds=self.job.write.lat_ns.max)

    def write_completion_latency_average(self):
        return Time(nanoseconds=self.job.write.lat_ns.mean)

    def write_completion_latency_percentile(self):
        return self.job.write.lat_ns.percentile.__dict__

    def write_requests_number(self):
        return self.result.disk_util[0].write_ios

    def trim_io(self):
        return Size(self.job.trim.io_kbytes, Unit.KibiByte)

    def trim_bandwidth(self):
        return Size(self.job.trim.bw, UnitPerSecond(Unit.KibiByte))

    def trim_bandwidth_average(self):
        return Size(self.job.trim.bw_mean, UnitPerSecond(Unit.KibiByte))

    def trim_bandwidth_deviation(self):
        return Size(self.job.trim.bw_dev, UnitPerSecond(Unit.KibiByte))

    def trim_iops(self):
        return self.job.trim.iops

    def trim_runtime(self):
        return Time(microseconds=self.job.trim.runtime)

    def trim_completion_latency_average(self):
        return Time(nanoseconds=self.job.trim.lat_ns.mean)

    def trim_completion_latency_min(self):
        return Time(nanoseconds=self.job.trim.lat_ns.min)

    def trim_completion_latency_max(self):
        return Time(nanoseconds=self.job.trim.lat_ns.max)

    def trim_completion_latency_average(self):
        return Time(nanoseconds=self.job.trim.lat_ns.mean)

    def trim_completion_latency_percentile(self):
        return self.job.trim.lat_ns.percentile.__dict__

    @staticmethod
    def result_list_to_dict(results):
        result_dict = {}

        for result in results:
            result_dict[result.job.jobname] = result.job

        return result_dict
