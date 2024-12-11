#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from collections import namedtuple

import test_tools.fs_tools
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from storage_devices.ramdisk import RamDisk
from test_utils.drbd import Resource, Node
from storage_devices.drbd import Drbd
from test_tools.drbdadm import Drbdadm
from test_tools import fs_tools
from test_tools.fs_tools import copy, Filesystem
from test_utils.filesystem.directory import Directory
from test_utils.filesystem.file import File
from type_def.size import Size, Unit
from test_utils.emergency_escape import EmergencyEscape
from test_tools.fstab import add_mountpoint
from storage_devices.lvm import Lvm


def setup_module():
    """
    Function called by python
    """
    TestRun.LOGGER.info("Entering setup method")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_create_example_partitions():
    """
        title: Example test creating partitions and filesystems.
        description: Create 6 partitions and create filesystem on each of them.
        pass_criteria:
          - Partitions are created with no error.
          - Filesystems are created successfully.
    """
    with TestRun.step("Prepare"):
        test_disk = TestRun.disks['cache']

    with TestRun.group("Repartition disk"):
        with TestRun.step("Generate partitions table"):
            part_sizes = []
            for i in range(1, 6):
                part_sizes.append(Size(10 * i + 100, Unit.MebiByte))
        with TestRun.step("Create partitions"):
            test_disk.create_partitions(part_sizes)
        for i in TestRun.iteration(range(0, 5)):
            with TestRun.step(f"Create filesystem on partition {i}"):
                test_tools.fs_utils.create_filesystem(Filesystem.ext3)


@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_raid_example():
    """
        title: Example test using RAID API.
        description: Create and discover RAID volumes.
        pass_criteria:
          - RAID created.
          - RAID discovered.
    """
    with TestRun.step("Prepare"):
        test_disk_1 = TestRun.disks['cache1']
        test_disk_2 = TestRun.disks['cache2']

    with TestRun.step("Create RAID"):
        config = RaidConfiguration(
            level=Level.Raid1,
            metadata=MetadataVariant.Imsm,
            number_of_devices=2,
            size=Size(20, Unit.GiB)
        )
        raid = Raid.create(config, [test_disk_1, test_disk_2])

    with TestRun.group("Discover RAIDs"):
        raids = Raid.discover()

    with TestRun.group("Check if created RAID was discovered"):
        if raid not in raids:
            TestRun.LOGGER.error("Created RAID not discovered in system!")


def test_create_example_files():
    """
        title: Example test manipulating on filesystem.
        description: Perform various operations on filesystem.
        pass_criteria:
          - System does not crash.
          - All operations complete successfully.
          - Data consistency is being preserved.
    """
    with TestRun.step("Create file with content"):
        file1 = File.create_file("example_file")
        file1.write("Test file\ncontent line\ncontent")
    with TestRun.step("Read file content"):
        content_before_change = file1.read()
        TestRun.LOGGER.info(f"File content: {content_before_change}")
    with TestRun.step("Replace single line in file"):
        fs_utils.replace_in_lines(file1, 'content line', 'replaced line')
    with TestRun.step("Read file content and check if it changed"):
        content_after_change = file1.read()
        if content_before_change == content_after_change:
            TestRun.fail("Content didn't changed as expected")

    with TestRun.step("Make copy of the file and check if md5 sum matches"):
        file2 = file1.copy('/tmp', force=True)
        if file1.md5sum() != file2.md5sum():
            TestRun.fail("md5 sum doesn't match!")
    with TestRun.step("Change permissions of second file"):
        file2.chmod_numerical(123)
    with TestRun.step("Remove second file"):
        fs_utils.remove(file2.full_path, True)

    with TestRun.step("List contents of home directory"):
        dir1 = Directory("~")
        dir_content = dir1.ls()
    with TestRun.step("Change permissions of file"):
        file1.chmod(fs_utils.Permissions['r'] | fs_utils.Permissions['w'],
                    fs_utils.PermissionsUsers(7))
    with TestRun.step("Log home directory content"):
        for item in dir_content:
            TestRun.LOGGER.info(f"Item {str(item)} - {type(item).__name__}")
    with TestRun.step("Remove file"):
        fs_utils.remove(file1.full_path, True)


@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.multidut(2)
def test_example_multidut():
    with TestRun.group("Run on all duts"):
        for dut in TestRun.duts:
            with TestRun.step("From TestRun.executor"):
                with TestRun.use_dut(dut):
                    TestRun.dut.hostname = TestRun.executor.run_expect_success('uname -n').stdout
                    TestRun.LOGGER.info(TestRun.dut.hostname)
            with TestRun.step("From returned executor"):
                with TestRun.use_dut(dut) as executor:
                    i = executor.run_expect_success("uname -i").stdout
                    TestRun.LOGGER.info(i)
    with TestRun.group("Run on single dut"):
        dut1, dut2 = TestRun.duts
        with TestRun.step(f"Run from TestRun.executor on dut {dut2.ip}"):
            with TestRun.use_dut(dut2):
                TestRun.LOGGER.info(TestRun.executor.run_expect_success("which casadm").stdout)
                for name, disk in TestRun.disks.items():
                    TestRun.LOGGER.info(f"{name}: {disk.path}")
        with TestRun.step(f"Run from returned executor on dut {dut1.ip}"):
            with TestRun.use_dut(dut1) as dut1_ex:
                TestRun.LOGGER.info(dut1_ex.run_expect_success("which casctl").stdout)
                for name, disk in TestRun.disks.items():
                    TestRun.LOGGER.info(f"{name}: {disk.path}")


@pytest.mark.require_disk("drbd_device", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.multidut(2)
def test_drbd_example():
    """
    title: Example test using DRBD API.
    description: Create primary and secondary resources on two DUTs using drbd.
    pass_criteria:
      - primary drbd resource created.
      - secondary drbd resource created.
    """
    with TestRun.step("Check if DRBD is installed"):
        for dut in TestRun.duts:
            with TestRun.use_dut(dut):
                if not Drbd.is_installed():
                    TestRun.fail(f"DRBD is not installed on DUT {dut.ip}")

    with TestRun.step("Prepare DUTs"):
        dut1, dut2 = TestRun.duts

        nodes = []
        for dut in TestRun.duts:
            with TestRun.use_dut(dut):
                TestRun.dut.hostname = TestRun.executor.run_expect_success("uname -n").stdout
                drbd_dev = TestRun.disks["drbd_device"]
                drbd_md_dev = RamDisk.create(Size(100, Unit.MebiByte), 1)[0]
                drbd_dev.create_partitions([Size(200, Unit.MebiByte)])
                drbd_dev = drbd_dev.partitions[0]

                nodes.append(
                    Node(TestRun.dut.hostname, drbd_dev.path, drbd_md_dev.path, dut.ip, "7790")
                )

        caches = Resource(name="caches", device="/dev/drbd0", nodes=nodes)

    with TestRun.step("Create DRBD config file on both DUTs"):
        for dut in TestRun.duts:
            with TestRun.use_dut(dut):
                TestRun.LOGGER.info(f"Saving config file on dut {dut.ip}")
                caches.save()

    with TestRun.use_dut(dut1), TestRun.step(f"Create a DRBD instance on {dut1}"):
        primary = Drbd(caches)
        primary.create_metadata(force=True)
        primary.up()

    with TestRun.use_dut(dut2), TestRun.step(f"Create a DRBD instance on {dut2}"):
        secondary = Drbd(caches)
        secondary.create_metadata(force=True)
        secondary.up()

    with TestRun.use_dut(dut1), TestRun.step(f"Set {dut1} as primary node"):
        primary.set_primary(force=True)

    with TestRun.use_dut(dut1), TestRun.step("Wait for drbd to sync"):
        primary.wait_for_sync()

    with TestRun.step("Test cleanup"):
        for dut in TestRun.duts:
            with TestRun.use_dut(dut):
                Drbdadm.down(caches.name)


def test_example_emergency_escape():
    """
    title: Example test EmergencyEscape class
    description: |
        Check if EmergencyEscape escapes emergency mode on DUT and leaves a verification marker
    pass_criteria:
      - DUT boots to default target after escaping emergency mode
      - verification marker present in dmesg
    """
    with TestRun.step("Create not-working mount"):
        FakeDevice = namedtuple("FakeDevice", ["path"])
        copy("/etc/fstab", "/root/fstab.bkup", force=True)
        dev = FakeDevice("/dev/not_existing_device")
        add_mountpoint(dev, "/not/a/mountpoint", Filesystem.xfs, mount_now=False)

    with TestRun.step("Configure emergency escape to restore working fstab from backup"):
        escape = EmergencyEscape()
        escape.add_escape_method_command("/usr/bin/cp /root/fstab.bkup /etc/fstab")
        escape.add_cleanup_method_command("/usr/bin/rm -f /root/fstab.bkup")

    with TestRun.step("Reboot with escape"):
        with escape:
            TestRun.executor.reboot()
            TestRun.executor.wait_for_connection()

    dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout.split("\n")
    assert escape.verify_trigger_in_log(
        dmesg_out
    ), "Emergency Escape trigger marker not found in dmesg"

    with TestRun.step("Reboot without escape"):
        TestRun.executor.reboot()
        TestRun.executor.wait_for_connection()

    dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout.split("\n")
    assert not escape.verify_trigger_in_log(
        dmesg_out
    ), "Emergency Escape trigger marker found in dmesg"


@pytest.mark.require_disk("cache1", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
@pytest.mark.require_disk("cache2", DiskTypeSet([DiskType.hdd, DiskType.hdd4k, DiskType.sata]))
def test_lvm_example():
    """
        title: Example test using LVM API.
        description: Create and discover Logical Volumes.
        pass_criteria:
          - LVMs created.
          - LVMs discovered.
    """
    with TestRun.step("Prepare"):
        disk_1 = TestRun.disks['cache1']
        disk_1.create_partitions([Size(8, Unit.GiB)] * 2)
        test_disk_1 = disk_1.partitions[0]
        test_disk_3 = disk_1.partitions[1]

        disk_2 = TestRun.disks['cache2']
        disk_2.create_partitions([Size(8, Unit.GiB)] * 2)
        test_disk_2 = disk_2.partitions[0]
        test_disk_4 = disk_2.partitions[1]

    with TestRun.step("Create LVMs"):
        lvm1 = Lvm.create(Size(5, Unit.GiB), [test_disk_1, test_disk_2], "lvm5")
        lvm2 = Lvm.create(70, [test_disk_3, test_disk_4], "lvm7")

    with TestRun.step("Discover LVMs"):
        lvms = Lvm.discover()

    with TestRun.step("Check if created LVMs were discovered"):
        for lvm in (lvm1, lvm2):
            if lvm not in lvms:
                TestRun.LOGGER.error(f"Created LVM {lvm.volume_name} not discovered in system!")

        TestRun.LOGGER.info(f"Created LVMs present in the system.")
