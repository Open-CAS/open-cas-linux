#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import datetime

from storage_devices.lvm import get_block_devices_list

from api.cas.init_config import InitConfig
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite, VerifyMethod
from test_utils.size import Size, Unit


def run_fio_on_lvm(volumes: []):
    fio_run = (Fio().create_command()
               .read_write(ReadWrite.randrw)
               .io_engine(IoEngine.sync)
               .io_depth(1)
               .time_based()
               .run_time(datetime.timedelta(seconds=180))
               .do_verify()
               .verify(VerifyMethod.md5)
               .block_size(Size(1, Unit.Blocks4096)))
    for lvm in volumes:
        fio_run.add_job().target(lvm).size(lvm.size)
    fio_run.run()


def get_test_configuration():
    config = InitConfig.create_init_config_from_running_configuration()
    devices = get_block_devices_list()

    return config, devices
