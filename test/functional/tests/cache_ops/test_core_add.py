#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from itertools import cycle
from random import shuffle
from api.cas import casadm
from api.cas.casadm_parser import get_cores
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils
from test_tools.fs_utils import remove, readlink
from test_utils.filesystem.symlink import Symlink
from test_utils.output import CmdException
from test_utils.size import Unit, Size

cores_number = 4


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_core_path_by_id():
    """
    title: Test for adding core with by-id path.
    description: |
      Check if OpenCAS accepts by-id path to disks added as cores.
    pass_criteria:
      - Cores are added to cache
      - Cores are added to cache with the same path as given
    """
    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, force=True)
        for i in range(cores_number):
            cache.add_core(core_dev.partitions[i])

    with TestRun.step("Check if all cores are added with proper paths."):
        added_cores = get_cores(cache.cache_id)
        added_cores_number = len(added_cores)
        if added_cores_number != cores_number:
            TestRun.fail(f"Expected {cores_number} cores, got {added_cores_number}!")

        for i, core in enumerate(added_cores):
            if core_dev.partitions[i].path != core.core_device.path:
                TestRun.LOGGER.error(
                    f"Paths are different and can cause problems!\n"
                    f"Path passed as an argument to add core: {core_dev.partitions[i].path}\n"
                    f"Path displayed by 'casadm -L': {core.core_device.path}"
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_core_path_not_by_id():
    """
    title: Negative test for adding core with non-by-id path.
    description: |
      Check if OpenCAS does not accept any other than by-id path to disks added as cores.
    pass_criteria:
      - Cores are not added to cache
    """

    symlink_path = '/tmp/castle'

    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step(
            f"Create symlinks for {core_dev.path} partitions in {symlink_path} directory."):
        core_dev_links = []
        for i, partition in enumerate(core_dev.partitions):
            path = readlink(partition.path)
            core_dev_links.append(
                Symlink.create_symlink(f"{symlink_path}_{path.split('/')[-1]}", path)
            )

    with TestRun.step(f"Find various symlinks to {core_dev.path}."):
        links = []
        for i in range(cores_number):
            links.append(Symlink(get_by_partuuid_link(core_dev.partitions[i].path)))
            links.append(Symlink(readlink(core_dev.partitions[i].path)))
            core_dev_links.extend([
                link for link in links if
                readlink(core_dev.partitions[i].path) in link.get_target()
            ])

    with TestRun.step(f"Select different links to {core_dev.path} partitions."):
        selected_links = select_random_links(core_dev_links)

    with TestRun.step(f"Try to add {cores_number} cores with non-by-id path."):
        for i in range(cores_number):
            core_dev.partitions[i].path = selected_links[i].full_path
            try:
                cache.add_core(core_dev.partitions[i])
                TestRun.fail(f"Core {core_dev.path} is added!")
            except CmdException:
                pass
        TestRun.LOGGER.info("Cannot add cores as expected.")

    with TestRun.step("Check if cores are not added."):
        added_cores_number = len(get_cores(cache.cache_id))
        if added_cores_number > 0:
            remove(f"{symlink_path}_*", True)
            TestRun.fail(f"Expected 0 cores, got {added_cores_number}!")

    with TestRun.step("Cleanup test symlinks."):
        fs_utils.remove(f"{symlink_path}_*", True, True)


def get_by_partuuid_link(path):
    output = TestRun.executor.run(f"blkid {path}")
    if "PARTUUID" not in output.stdout:
        return path

    uuid = output.stdout.split()[-1]
    start = uuid.index('"')
    end = uuid.index('"', start + 1)
    uuid = uuid[start + 1:end]

    return f"/dev/disk/by-partuuid/{uuid}"


def select_random_links(links):
    shuffle(links)
    selected_links = []
    links_cycle = cycle(links)

    while len(selected_links) < cores_number:
        link = next(links_cycle)
        target = link.get_target()
        if target not in [sel_link.get_target() for sel_link in selected_links]:
            selected_links.append(link)

    return selected_links
