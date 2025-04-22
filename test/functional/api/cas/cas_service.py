#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

from pathlib import PurePosixPath
from datetime import timedelta
from string import Template
from textwrap import dedent

from test_tools.fs_tools import (
    check_if_directory_exists,
    create_directory,
    write_file,
    remove,
)
from test_tools.systemctl import reload_daemon

opencas_drop_in_directory = PurePosixPath("/etc/systemd/system/open-cas.service.d/")
test_drop_in_file = PurePosixPath("10-modified-timeout.conf")

drop_in_timeout_template = Template(
    dedent(
        """
        [Service]
        ExecStart=
        ExecStart=/bin/sh -c '/usr/bin/echo "Default open-cas.service config overwritten by test!" > /dev/kmsg'
        ExecStart=-/sbin/casctl settle --timeout $timeout --interval 1
        TimeoutStartSec=$timeout
        """
    ).strip()
)


def set_cas_service_timeout(timeout: timedelta = timedelta(minutes=30)):
    if not check_if_directory_exists(opencas_drop_in_directory):
        create_directory(opencas_drop_in_directory, parents=True)

    contents = drop_in_timeout_template.substitute(timeout=timeout.seconds)

    write_file(str(opencas_drop_in_directory / test_drop_in_file), contents)
    reload_daemon()


def clear_cas_service_timeout():
    remove(str(opencas_drop_in_directory), force=True, recursive=True, ignore_errors=True)
    reload_daemon()
