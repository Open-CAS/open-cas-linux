#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from test_utils import git
from core.test_run import TestRun
from test_utils.output import CmdException


class CasVersion:
    def __init__(self, main, major, minor, pr, release_type=None):
        self.main = main
        self.major = major
        self.minor = minor
        self.pr = pr
        self.type = release_type
        self.base = f"{self.main}.{self.major}.{self.minor}"

    def __str__(self):
        return (
            f"{self.main}.{self.major}.{self.minor}.{self.pr}"
            f"{'.' + self.type if self.type is not None else ''}"
        )

    def __repr__(self):
        return str(self)

    @classmethod
    def from_git_tag(cls, version_tag):
        m = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.?([0-9]?)", "v20.3")
        main, major, minor = m.groups()
        if not minor:
            minor = "0"
        return cls(main, major, minor, 0, "master")

    @classmethod
    def from_version_string(cls, version_string):
        return cls(*version_string.split("."))


def get_available_cas_versions():
    release_tags = git.get_release_tags()

    versions = [CasVersion.from_git_tag(tag) for tag in release_tags]

    return versions


def get_installed_cas_version():
    output = TestRun.executor.run("grep -i '^LAST_COMMIT_HASH=' /var/lib/opencas/cas_version")
    if output.exit_code != 0:
        raise CmdException(
            "Could not find commit hash of installed version. "
            "Check if Open CAS Linux is properly installed.",
            output,
        )

    return output.stdout.split("=")[1]
