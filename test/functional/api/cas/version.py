#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os

from api.cas import git
from packaging import version


class CasVersion(version.Version):
    def can_be_upgraded(self):
        return self >= CasVersion("v20.1")

    def __str__(self):
        return f"v{super().__str__()}"

    def __repr__(self):
        return str(self)


def get_available_cas_versions():
    release_tags = git.get_release_tags()

    versions = [CasVersion(tag) for tag in release_tags]

    return versions


def get_upgradable_cas_versions():
    return [v for v in get_available_cas_versions() if v.can_be_upgraded()]
