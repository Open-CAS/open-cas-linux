#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


from itertools import product
from git import Repo, Commit
from packaging import version
import os

from api.cas.cas_module import CasModule
from test_utils.os_utils import get_module_path, get_executable_path, get_udev_service_path


class CasVersion(version.Version):
    def __str__(self):
        return f"v{super().__str__()}"

    def __repr__(self):
        return str(self)


def get_available_cas_versions(cas_repo: Repo):
    versions = sorted(set([CasVersion(str(tag).split('-')[0]) for tag in cas_repo.tags]))

    return versions


def get_upgradable_cas_versions(to: Commit):
    repo = to.repo

    return [v for v in get_available_cas_versions(repo) if cas_can_be_upgraded(from_=v, to=to)]


def find_last_release_tag(commit: Commit):
    """Find last release tag created before given commit"""
    cas_repo = commit.repo

    tags = [t for t in cas_repo.tags if t.commit.committed_datetime < commit.committed_datetime]
    # In case tag name is sth like `v20.3-multistream-sequential-cutoff`
    tags = [t for t in tags if '-' not in t.name]
    tags.sort(key=lambda tag: tag.commit.committed_datetime)

    last_release_tag = tags[-1].name

    return last_release_tag


def cas_can_be_upgraded(from_: CasVersion, to: Commit):
    """ Test if one of CAS release versions can be upgraded to particular commit """
    cas_repo = to.repo

    latest_version = CasVersion(find_last_release_tag(commit=to))

    # In case CAS would be upgradable only between range of versions,
    # new check should like following:
    #
    # if min_ver <= latest_version <= max_version and min_ver <= from_ <= max_version:
    #    return True
    #
    # For each range of upgradable versions such check should be implemented

    __20_1 = CasVersion("20.1")
    # TODO if final version upgradable from v20.1 is developed, this condition should be updated
    if from_ >= __20_1 and latest_version >= __20_1:
        return True

    return False


def get_installed_files_list(v: CasVersion):
    if v >= CasVersion("v20.1"):
        return __20_1_installed_files_list()

    if v >= CasVersion("v19.9"):
        return __19_9_installed_files_list()

    raise ValueError(f"List of installed files for CAS {v} is not specified")


def __20_1_installed_files_list():
    paths = __19_9_installed_files_list()

    paths.append(get_udev_service_path("open-cas"))

    return paths


def __19_9_installed_files_list():
    casctl_dir = "/lib/opencas"
    udevrules_dir = "/lib/udev/rules.d"
    man_dir = "/usr/share/man"

    casctl_files = ["casctl", "open-cas-loader", "opencas.py"]
    udevrules_files = [
        "60-persistent-storage-cas-load.rules",
        "60-persistent-storage-cas.rules",
    ]
    man_files = ["man5/opencas.conf.5", "man8/casadm.8", "man8/casctl.8"]

    paths = [get_module_path(CasModule.cache.value)]
    paths.append(get_module_path(CasModule.disk.value))
    paths.append(get_executable_path("casctl"))
    paths.append(get_executable_path("casadm"))
    paths.append(get_udev_service_path("open-cas-shutdown"))
    paths.append(get_executable_path("casadm"))
    paths += [os.path.join(casctl_dir, f) for f in casctl_files]
    paths += [os.path.join(udevrules_dir, f) for f in udevrules_files]
    paths += [os.path.join(man_dir, f) for f in man_files]

    return paths
