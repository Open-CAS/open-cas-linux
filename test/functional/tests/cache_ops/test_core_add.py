#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import os
from itertools import cycle
from random import shuffle

import pytest

from api.cas import casadm
from api.cas.casadm_parser import get_cores
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_utils import parse_ls_output, ls, remove, readlink
from test_utils.filesystem.symlink import Symlink
from test_utils.output import CmdException
from test_utils.size import Unit, Size

cores_number = 4
by_id_dir = '/dev/disk/by-id/'
custom_dir = '/tmp/castle'
symlink_name = 'dinosaur'


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
    with TestRun.step("Clearing dmesg"):
        TestRun.executor.run_expect_success("dmesg -C")

    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step(
            f"Create symlinks for {core_dev.path} partitions in {by_id_dir} directory."
    ):
        for i, partition in enumerate(core_dev.partitions):
            Symlink.create_symlink(by_id_dir, partition.path)

    with TestRun.step(f"Find symlinks to {core_dev.path} in {by_id_dir}."):
        links = [
            Symlink(os.path.join(by_id_dir, item.full_path))       # parse_ls_output returns
            for item in parse_ls_output(ls(by_id_dir), by_id_dir)  # symlinks without path
            if isinstance(item, Symlink)
        ]
        core_dev_links = [link for link in links if readlink(core_dev.path) in link.get_target()]

    with TestRun.step(f"Select different links to {core_dev.path} partitions."):
        selected_links = select_links(core_dev_links)

    with TestRun.step("Start cache and add cores"):
        paths_from_dmesg = []
        cache = casadm.start_cache(cache_part, force=True)
        for i in range(cores_number):
            core_dev.partitions[i].path = selected_links[i].full_path
            cache.add_core(core_dev.partitions[i])
            paths_from_dmesg.append(get_added_core_path_from_dmesg())

    with TestRun.step("Check if all cores are added."):
        added_cores_number = len(get_cores(cache.cache_id))
        if added_cores_number != cores_number:
            remove(f"{os.path.join(by_id_dir, symlink_name)}*", True)
            TestRun.fail(f"Expected {cores_number} cores, got {added_cores_number}!")

    with TestRun.step("Compare paths to cores."):
        for i in range(cores_number):
            if paths_from_dmesg[i] != selected_links[i].full_path:
                TestRun.LOGGER.error(
                    f"Paths are different and can cause problems!\n"
                    f"Path passed as an argument to add core: {selected_links[i].full_path}\n"
                    f"Path currently used in core addition: {paths_from_dmesg[i]}"
                )

    with TestRun.step("Cleanup test symlinks."):
        remove(f"{os.path.join(by_id_dir, symlink_name)}*", True)


def select_links(links):
    selected_links = []
    prev_starts_with = " "
    prev_ends_with = " "
    links_cycle = cycle(links)

    while len(selected_links) < cores_number:
        link = next(links_cycle)
        if '-part' not in link.name:
            continue
        if (
                link.get_target() not in [sel_link.get_target() for sel_link in selected_links]
                and not link.name.startswith(prev_starts_with)
                and not link.name.endswith(prev_ends_with)
        ):
            selected_links.append(link)
            prev_ends_with = link.name.split('-')[-1]
            prev_starts_with = link.name[:(link.name.index(prev_ends_with) - 1)]

    return selected_links


def get_added_core_path_from_dmesg():
    output = TestRun.executor.run_expect_success("dmesg -c")
    path_line = [
        line for line in reversed(output.stdout.splitlines()) if 'as core' in line
    ][0]
    path = [item for item in path_line.split() if '/dev/disk/by-id/' in item][0]
    return path


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
    with TestRun.step("Prepare partitions for cache and for cores."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache."):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step(f"Create symlinks for {core_dev.path} partitions in {custom_dir} directory."):
        for i, partition in enumerate(core_dev.partitions):
            Symlink.create_symlink(custom_dir, readlink(partition.path))

    with TestRun.step(f"Find various symlinks to {core_dev.path}."):
        core_dev_links = []
        links = [
            Symlink(os.path.join(custom_dir, item.full_path))       # parse_ls_output returns
            for item in parse_ls_output(ls(custom_dir), custom_dir)  # symlinks without path
            if isinstance(item, Symlink)
        ]

        for i in range(cores_number):
            links.append(Symlink(get_by_partuuid_link(core_dev.partitions[i].path)))
            links.append(Symlink(readlink(core_dev.partitions[i].path)))
            core_dev_links.extend([
                link for link in links if readlink(core_dev.partitions[i].path) in link.get_target()
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
            remove(f"{os.path.join(custom_dir, symlink_name)}*", True)
            TestRun.fail(f"Expected 0 cores, got {added_cores_number}!")

    with TestRun.step("Cleanup test symlinks."):
        remove(f"{os.path.join(custom_dir, symlink_name)}*", True)


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
    prev_ends_with = " "
    links_cycle = cycle(links)

    while len(selected_links) < cores_number:
        link = next(links_cycle)
        target = link.get_target()
        if 'p' not in target:
            continue
        if (
                target not in [sel_link.get_target() for sel_link in selected_links]
                and not target.endswith(prev_ends_with)
        ):
            selected_links.append(link)
            prev_ends_with = target.split('p')[-1]

    return selected_links
