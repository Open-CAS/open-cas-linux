#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from itertools import cycle
from random import shuffle
from api.cas import casadm
from api.cas.casadm_parser import get_cores, get_detached_cores, get_inactive_cores
from connection.utils.output import CmdException
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_tools import readlink, remove
from test_utils.filesystem.symlink import Symlink
from type_def.size import Size, Unit

cores_number = 4


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_core_path_by_id():
    """
    title: Test for adding core with by-id path.
    description: |
        Check if core can be added to cache using by-id path.
    pass_criteria:
      - Cores are added to cache
      - Cores are added to cache with the same path as given
    """
    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, force=True)
        for core_dev_part in core_dev.partitions:
            cache.add_core(core_dev_part)

    with TestRun.step("Check if all cores are added with proper paths."):
        added_cores = get_cores(cache.cache_id)
        added_cores_number = len(added_cores)
        if added_cores_number != cores_number:
            TestRun.fail(f"Expected {cores_number} cores, got {added_cores_number}!")

        for core, partition in zip(added_cores, core_dev.partitions):
            if partition.path != core.core_device.path:
                TestRun.LOGGER.error(
                    f"Paths are different and can cause problems!\n"
                    f"Path passed as an argument to add core: {partition.path}\n"
                    f"Path displayed by 'casadm -L': {core.core_device.path}"
                )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_add_core_path_not_by_id():
    """
    title: Negative test for adding core with non-by-id path.
    description: |
        Check if it is not permitted to use any other than by-id path to disks added as cores.
    pass_criteria:
      - Cores are not added to cache
    """

    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step(
            f"Create symlinks for {core_dev.path} partitions in "
            f"{TestRun.TEST_RUN_DATA_PATH} directory."
    ):
        core_dev_links = [
            Symlink.create_symlink(
                f"{TestRun.TEST_RUN_DATA_PATH}_{path.split('/')[-1]}",
                path
            ) for path in [readlink(part.path) for part in core_dev.partitions]
        ]

    with TestRun.step(f"Find various symlinks to {core_dev.path}."):
        links = []
        for partition in core_dev.partitions:
            links.append(Symlink(get_by_partuuid_link(partition.path)))
            links.append(Symlink(readlink(partition.path)))
            core_dev_links.extend([
                link for link in links if
                readlink(partition.path) in link.get_target()
            ])

    with TestRun.step(f"Select different links to {core_dev.path} partitions."):
        selected_links = select_random_links(core_dev_links)

    with TestRun.step(f"Try to add {cores_number} cores with non-by-id path."):
        for dev, symlink in zip(core_dev.partitions, selected_links):
            dev.path = symlink.full_path
            try:
                cache.add_core(dev)
                TestRun.fail(f"Core {core_dev.path} is added!")
            except CmdException:
                pass
        TestRun.LOGGER.info("Cannot add cores as expected.")

    with TestRun.step("Check if cores are not added."):
        get_core_methods = [get_cores, get_inactive_cores, get_detached_cores]
        core_types = ["active", "inactive", "detached"]
        for method, core_type in zip(get_core_methods, core_types):
            added_cores_number = len(method(cache.cache_id))
            if added_cores_number > 0:
                TestRun.LOGGER.error(
                    f"Expected 0 cores, got {added_cores_number} {core_type} cores!"
                )

    with TestRun.step("Cleanup test symlinks."):
        remove(f"{TestRun.TEST_RUN_DATA_PATH}_*", True, True)


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
