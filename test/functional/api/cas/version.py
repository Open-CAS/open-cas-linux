#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#


from itertools import product
from git import Repo, Commit
from packaging import version
import os


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
