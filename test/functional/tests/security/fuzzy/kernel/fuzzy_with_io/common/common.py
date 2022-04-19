#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
from datetime import timedelta

from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_utils.size import Size, Unit


def get_basic_workload(mount_point: str):
    file_min_size = Size(10, Unit.Byte).get_value()
    file_max_size = Size(512, Unit.KiB).get_value()
    fio = (Fio()
           .create_command()
           .io_engine(IoEngine.libaio)
           .direct()
           .run_time(timedelta(days=1))
           .time_based()
           .directory(mount_point)
           .read_write(ReadWrite.randrw)
           .nr_files(1000)
           .file_size_range([(file_min_size, file_max_size)])
           .num_jobs(32))
    return fio
