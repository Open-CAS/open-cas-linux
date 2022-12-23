#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from textwrap import dedent
from string import Template
from pathlib import Path

from .systemd import enable_service, reload_daemon, systemd_service_directory, disable_service
from test_tools.fs_utils import (
    create_file,
    write_file,
    remove,
)


class EmergencyEscape:
    escape_marker = "EMERGENCY_ESCAPE"
    escape_service = Path("emergency-escape.service")
    escape_service_template = Template(
        dedent(
            f"""
            [Unit]
            After=emergency.target
            IgnoreOnIsolate=true
            DefaultDependencies=no

            [Service]
            Type=oneshot
            ExecStart=/bin/sh -c '/usr/bin/echo "{escape_marker}" > /dev/kmsg'
            $user_method
            ExecStart=/usr/bin/systemctl daemon-reload
            ExecStart=/usr/bin/systemctl default --no-block

            [Install]
            WantedBy=emergency.target
            """
        ).strip()
    )
    cleanup_service = Path("emergency-escape-cleanup.service")
    cleanup_service_template = Template(
        dedent(
            """
            [Unit]
            After=emergency-escape.service
            IgnoreOnIsolate=true
            DefaultDependencies=no

            [Service]
            Type=oneshot
            $user_method
            ExecStart=/usr/bin/systemctl disable emergency-escape.service
            ExecStart=/usr/bin/rm -f /usr/lib/systemd/system/emergency-escape.service
            ExecStart=/usr/bin/systemctl daemon-reload

            [Install]
            WantedBy=emergency-escape.service
            """
        ).strip()
    )

    def __init__(self):
        self.escape_method = []
        self.cleanup_method = []

    def arm(self):
        escape_path = str(systemd_service_directory / EmergencyEscape.escape_service)
        cleanup_path = str(systemd_service_directory / EmergencyEscape.cleanup_service)

        create_file(escape_path)
        create_file(cleanup_path)

        user_escape = "\n".join([f"ExecStart={method}" for method in self.escape_method])
        user_cleanup = "\n".join([f"ExecStart={method}" for method in self.cleanup_method])

        escape_contents = EmergencyEscape.escape_service_template.substitute(
            user_method=user_escape
        )
        cleanup_contents = EmergencyEscape.cleanup_service_template.substitute(
            user_method=user_cleanup
        )

        write_file(escape_path, escape_contents)
        write_file(cleanup_path, cleanup_contents)

        enable_service(EmergencyEscape.escape_service)
        enable_service(EmergencyEscape.cleanup_service)

    def cleanup(self):
        remove(str(systemd_service_directory / EmergencyEscape.cleanup_service), ignore_errors=True)
        remove(str(systemd_service_directory / EmergencyEscape.escape_service), ignore_errors=True)
        reload_daemon()

    @classmethod
    def verify_trigger_in_log(cls, log_list):
        for l in log_list:
            if cls.escape_marker in l:
                return True

        return False

    def add_escape_method_command(self, method):
        self.escape_method.append(method)

    def add_cleanup_method_command(self, method):
        self.cleanup_method.append(method)

    def __enter__(self):
        self.arm()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.cleanup()
