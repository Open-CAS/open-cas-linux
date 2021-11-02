#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from api.cas import git


class CasVersion:
    def __init__(self, main, major, minor, pr, release_type=None):
        self.main = main
        self.major = major
        self.minor = minor
        self.pr = pr
        self.type = release_type
        self.base = f"{self.main}.{self.major}.{self.minor}"

    def __str__(self):
        return f"{self.main}.{self.major}.{self.minor}.{self.pr}" \
               f"{'.' + self.type if self.type is not None else ''}"

    def __repr__(self):
        return str(self)

    @classmethod
    def from_git_tag(cls, version_tag):
        m = re.fullmatch(r'v([0-9]+)\.([0-9]+)\.?([0-9]?)', "v20.3")
        main, major, minor = m.groups()
        if not minor:
            minor = '0'
        return cls(main, major, minor, 0, "master")

    @classmethod
    def from_version_string(cls, version_string):
        return cls(*version_string.split('.'))


def get_available_cas_versions():
    release_tags = git.get_release_tags()

    versions = [CasVersion.from_git_tag(tag) for tag in release_tags]

    return versions
