#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from time import sleep
import pytest

from api.cas import casadm
from api.cas.cache_config import (
    SeqCutOffPolicy,
    CacheMode,
    CleaningPolicy,
    CacheLineSize,
    CacheStatus,
)
from api.cas.casadm_parser import get_caches
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.drbd import Drbd
from storage_devices.raid import Raid, RaidConfiguration, MetadataVariant, Level
from test_tools.dd import Dd
from test_tools.drbdadm import Drbdadm
from test_tools.disk_utils import Filesystem
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite
from test_tools.fs_utils import readlink
from test_utils.drbd import Resource, Node
from test_utils.os_utils import sync, Udev
from test_utils.size import Size, Unit
from test_tools import fs_utils


cache_id = 5
raid_size = Size(1, Unit.GibiByte)
core_size = Size(500, Unit.MebiByte)
metadata_size = Size(100, Unit.MebiByte)
cache_exp_obj_path = f"/dev/cas-cache-{cache_id}"
cls = CacheLineSize.LINE_32KiB
mountpoint = "/tmp/drbd_functional_test"
test_file_path = f"{mountpoint}/test_file"


@pytest.mark.require_disk("metadata_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.hdd]))
@pytest.mark.require_disk("raid_dev1", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("raid_dev2", DiskTypeSet([DiskType.optane]))
@pytest.mark.multidut(2)
@pytest.mark.require_plugin("power_control")
@pytest.mark.parametrize("filesystem", [Filesystem.xfs, None])
def test_functional_activate_twice_round_trip(filesystem):
    """
    title:  Cache replication.
    description:
      Restore cache operations from a replicated cache and make sure
      second failover is possible to return to original configuration
    pass_criteria:
      - A cache exported object appears after starting a cache in passive state
      - The cache exported object can be used for replicating a cache device
      - The cache exported object disappears after the cache activation
      - The core exported object reappears after the cache activation
      - A data integrity check passes for the core exported object before and after
        switching cache instances
      - CAS standby cahce starts automatically after starting OS when configured
        in CAS config
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts
        extra_init_config_flags = (
            f"cache_line_size={str(cls.value.value//1024)},target_failover_state=standby"
        )
        primary_init_config = InitConfig()
        primary_init_config.add_cache(
            cache_id,
            primary_node.raid,
            CacheMode.WB,
            extra_flags=extra_init_config_flags,
        )
        secondary_init_config = InitConfig()
        secondary_init_config.add_cache(
            cache_id,
            secondary_node.raid,
            CacheMode.WB,
            extra_flags=extra_init_config_flags,
        )

    # THIS IS WHERE THE REAL TEST STARTS
    TestRun.LOGGER.start_group(
        f"Initial configuration with {primary_node.ip} as primary node "
        f"and {secondary_node.ip} as secondary node"
    )

    with TestRun.use_dut(secondary_node), TestRun.step(
        f"Prepare standby cache instance on {secondary_node.ip}"
    ):
        secondary_node.cache = casadm.standby_init(
            cache_dev=secondary_node.raid,
            cache_line_size=str(cls.value.value // 1024),
            cache_id=cache_id,
            force=True,
        )

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        caches_original_resource, caches_failover_resource, cores_resource = get_drbd_configs(
            primary_node, secondary_node
        )

    for dut in TestRun.duts:
        with TestRun.use_dut(dut), TestRun.step(f"Create DRBD instances on {dut.ip}"):
            caches_original_resource.save()
            dut.cache_drbd = Drbd(caches_original_resource)
            dut.cache_drbd.create_metadata()
            dut.cache_drbd_dev = dut.cache_drbd.up()

            cores_resource.save()
            dut.core_drbd = Drbd(cores_resource)
            dut.core_drbd.create_metadata()
            dut.core_drbd_dev = dut.core_drbd.up()

    with TestRun.use_dut(primary_node), TestRun.step(
        f"Set {primary_node.ip} as primary node for both DRBD instances"
    ):
        primary_node.cache_drbd.set_primary(force=True)
        primary_node.core_drbd.set_primary(force=True)

    with TestRun.use_dut(primary_node), TestRun.step("Make sure drbd instances are in sync"):
        primary_node.cache_drbd.wait_for_sync()
        primary_node.core_drbd.wait_for_sync()

    with TestRun.use_dut(primary_node), TestRun.step(f"Start cache on {primary_node.ip}"):
        primary_node.cache = casadm.start_cache(
            primary_node.cache_drbd_dev,
            force=True,
            cache_mode=CacheMode.WB,
            cache_line_size=cls,
            cache_id=cache_id,
        )
        core = primary_node.cache.add_core(primary_node.core_drbd_dev)
        primary_node.cache.set_cleaning_policy(CleaningPolicy.nop)
        primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        if filesystem:
            TestRun.executor.run(f"rm -rf {mountpoint}")
            fs_utils.create_directory(path=mountpoint)
            core.create_filesystem(filesystem)
            core.mount(mountpoint)

    with TestRun.use_dut(primary_node), TestRun.step(
        f"Prepare standby init config on {primary_node.ip}"
    ):
        primary_init_config.save_config_file()
        sync()

    with TestRun.use_dut(primary_node), TestRun.step("Fill core with data randrwmix=50%"):
        fio = Fio().create_command().read_write(ReadWrite.randrw).size(core_size * 0.9)
        fio.file_name(test_file_path) if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    data_path = test_file_path if filesystem else core.path
    original_core_md5, original_cache_stats = power_failure(primary_node, data_path)

    TestRun.LOGGER.end_group()
    TestRun.LOGGER.start_group(
        f"First failover sequence. {secondary_node.ip} becomes"
        f" primary node and {primary_node.ip} becomes secondary node"
    )

    failover_sequence(secondary_node, caches_failover_resource, filesystem, core)

    with TestRun.use_dut(secondary_node), TestRun.step(
        f"Prepare standby init config on {secondary_node.ip}"
    ):
        secondary_init_config.save_config_file()
        sync()

    postfailover_check(secondary_node, data_path, original_core_md5, original_cache_stats)

    with TestRun.use_dut(secondary_node), TestRun.step(
        "Fill half of the core with data randrwmix=50%"
    ):
        fio = Fio().create_command().read_write(ReadWrite.randrw).size(core_size * 0.5)
        fio.file_name(f"{mountpoint}/test_file") if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    with TestRun.use_dut(primary_node), TestRun.step(f"Restore core DRBD on {primary_node.ip}"):
        TestRun.executor.wait_for_connection()
        primary_node.core_drbd_dev = primary_node.core_drbd.up()

    new_failover_instance(primary_node, caches_failover_resource, autoload=True)

    with TestRun.use_dut(secondary_node), TestRun.step(
        "Fill the second half of the core with data randrwmix=50%"
    ):
        fio = (
            Fio()
            .create_command()
            .read_write(ReadWrite.randrw)
            .size(core_size * 0.4)
            .offset(core_size * 0.5)
        )
        fio.file_name(f"{mountpoint}/test_file") if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    original_core_md5, original_cache_stats = power_failure(secondary_node, data_path)

    TestRun.LOGGER.end_group()
    TestRun.LOGGER.start_group(
        f"Second failover sequence. {primary_node.ip} becomes"
        f" primary node and {secondary_node.ip} becomes secondary node"
    )

    failover_sequence(primary_node, caches_original_resource, filesystem, core)

    postfailover_check(primary_node, data_path, original_core_md5, original_cache_stats)

    with TestRun.use_dut(secondary_node):
        TestRun.executor.wait_for_connection()

    TestRun.LOGGER.end_group()


@pytest.mark.require_disk("metadata_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.hdd]))
@pytest.mark.require_disk("raid_dev1", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("raid_dev2", DiskTypeSet([DiskType.optane]))
@pytest.mark.multidut(2)
@pytest.mark.require_plugin("power_control")
@pytest.mark.parametrize("filesystem", [Filesystem.xfs, None])
def test_functional_activate_twice_new_host(filesystem):
    """
    title:  Cache replication.
    description:
      Restore cache operations from a replicated cache and make sure
      second failover is possible to return to original configuration
    pass_criteria:
      - A cache exported object appears after starting a cache in passive state
      - The cache exported object can be used for replicating a cache device
      - The cache exported object disappears after the cache activation
      - The core exported object reappears after the cache activation
      - A data integrity check passes for the core exported object before and after
        switching cache instances
      - CAS standby cahce starts automatically after starting OS when configured
        in CAS config
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts
        extra_init_config_flags = (
            f"cache_line_size={str(cls.value.value//1024)},target_failover_state=standby"
        )

    # THIS IS WHERE THE REAL TEST STARTS
    TestRun.LOGGER.start_group(
        f"Initial configuration with {primary_node.ip} as primary node "
        f"and {secondary_node.ip} as secondary node"
    )

    with TestRun.use_dut(secondary_node), TestRun.step(
        f"Prepare standby cache instance on {secondary_node.ip}"
    ):
        secondary_node.cache = casadm.standby_init(
            cache_dev=secondary_node.raid,
            cache_line_size=str(cls.value.value // 1024),
            cache_id=cache_id,
            force=True,
        )

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        caches_original_resource, caches_failover_resource, cores_resource = get_drbd_configs(
            primary_node, secondary_node
        )

    for dut in TestRun.duts:
        with TestRun.use_dut(dut), TestRun.step(f"Create DRBD instances on {dut.ip}"):
            caches_original_resource.save()
            dut.cache_drbd = Drbd(caches_original_resource)
            dut.cache_drbd.create_metadata()
            dut.cache_drbd_dev = dut.cache_drbd.up()

            cores_resource.save()
            dut.core_drbd = Drbd(cores_resource)
            dut.core_drbd.create_metadata()
            dut.core_drbd_dev = dut.core_drbd.up()

    with TestRun.use_dut(primary_node), TestRun.step(
        f"Set {primary_node.ip} as primary node for both DRBD instances"
    ):
        primary_node.cache_drbd.set_primary(force=True)
        primary_node.core_drbd.set_primary(force=True)

    with TestRun.use_dut(primary_node), TestRun.step("Make sure drbd instances are in sync"):
        primary_node.cache_drbd.wait_for_sync()
        primary_node.core_drbd.wait_for_sync()

    with TestRun.use_dut(primary_node), TestRun.step(f"Start cache on {primary_node.ip}"):
        primary_node.cache = casadm.start_cache(
            primary_node.cache_drbd_dev,
            force=True,
            cache_mode=CacheMode.WB,
            cache_line_size=cls,
            cache_id=cache_id,
        )
        core = primary_node.cache.add_core(primary_node.core_drbd_dev)
        primary_node.cache.set_cleaning_policy(CleaningPolicy.nop)
        primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        if filesystem:
            TestRun.executor.run(f"rm -rf {mountpoint}")
            fs_utils.create_directory(path=mountpoint)
            core.create_filesystem(filesystem)
            core.mount(mountpoint)

    with TestRun.use_dut(primary_node), TestRun.step("Fill core with data randrwmix=50%"):
        fio = Fio().create_command().read_write(ReadWrite.randrw).size(core_size * 0.9)
        fio.file_name(test_file_path) if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    data_path = test_file_path if filesystem else core.path
    original_core_md5, original_cache_stats = power_failure(primary_node, data_path)

    TestRun.LOGGER.end_group()
    TestRun.LOGGER.start_group(
        f"First failover sequence. {secondary_node.ip} becomes"
        f" primary node and {primary_node.ip} becomes secondary node"
    )

    failover_sequence(secondary_node, caches_failover_resource, filesystem, core)

    postfailover_check(secondary_node, data_path, original_core_md5, original_cache_stats)

    with TestRun.use_dut(secondary_node), TestRun.step(
        "Fill half of the core with data randrwmix=50%"
    ):
        fio = Fio().create_command().read_write(ReadWrite.randrw).size(core_size * 0.5)
        fio.file_name(f"{mountpoint}/test_file") if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    with TestRun.use_dut(primary_node), TestRun.step(f"Restore core DRBD on {primary_node.ip}"):
        TestRun.executor.wait_for_connection()
        primary_node.core_drbd_dev = primary_node.core_drbd.up()

    new_failover_instance(primary_node, caches_failover_resource, autoload=False)

    with TestRun.use_dut(secondary_node), TestRun.step(
        "Fill the second half of the core with data randrwmix=50%"
    ):
        (
            Fio()
            .create_command()
            .read_write(ReadWrite.randrw)
            .size(core_size * 0.4)
            .offset(core_size * 0.5)
        ).run()
        fio.file_name(f"{mountpoint}/test_file") if filesystem else fio.target(core.path).direct()
        fio.run()
        sync()

    original_core_md5, original_cache_stats = power_failure(secondary_node, data_path)

    TestRun.LOGGER.end_group()
    TestRun.LOGGER.start_group(
        f"Second failover sequence. {primary_node.ip} becomes"
        f" primary node and {secondary_node.ip} becomes secondary node"
    )

    failover_sequence(primary_node, caches_original_resource, filesystem, core)

    postfailover_check(primary_node, data_path, original_core_md5, original_cache_stats)

    with TestRun.use_dut(secondary_node):
        TestRun.executor.wait_for_connection()

    TestRun.LOGGER.end_group()


def check_drbd_installed(duts):
    for dut in duts:
        with TestRun.use_dut(dut):
            if not Drbd.is_installed():
                TestRun.fail(f"DRBD is not installed on DUT {dut.ip}")


def prepare_devices(duts):
    for dut in duts:
        with TestRun.use_dut(dut):
            TestRun.dut.hostname = TestRun.executor.run_expect_success("uname -n").stdout

            raid_members = [TestRun.disks["raid_dev1"], TestRun.disks["raid_dev2"]]
            for d in raid_members:
                d.create_partitions([raid_size * 1.1])  # extra space for RAID metadata

            raid_config = RaidConfiguration(
                level=Level.Raid1,
                metadata=MetadataVariant.Legacy,
                number_of_devices=2,
                size=raid_size,
            )
            dut.raid = Raid.create(raid_config, [d.partitions[0] for d in raid_members])
            dut.raid_path = readlink(dut.raid.path)

            TestRun.disks["metadata_dev"].create_partitions([metadata_size] * 2)
            dut.cache_md_dev = TestRun.disks["metadata_dev"].partitions[0]
            dut.core_md_dev = TestRun.disks["metadata_dev"].partitions[1]

            TestRun.disks["core_dev"].create_partitions([core_size])
            dut.core_dev = TestRun.disks["core_dev"].partitions[0]


def get_drbd_configs(n1, n2):
    cache_original_drbd_nodes = [
        Node(n1.hostname, n1.raid_path, n1.cache_md_dev.path, n1.ip, "7790"),
        Node(n2.hostname, cache_exp_obj_path, n2.cache_md_dev.path, n2.ip, "7790"),
    ]
    cache_failover_drbd_nodes = [
        Node(n1.hostname, cache_exp_obj_path, n1.cache_md_dev.path, n1.ip, "7790"),
        Node(n2.hostname, n2.raid_path, n2.cache_md_dev.path, n2.ip, "7790"),
    ]
    core_drbd_nodes = [
        Node(dut.hostname, dut.core_dev.path, dut.core_md_dev.path, dut.ip, "7791")
        for dut in [n1, n2]
    ]

    caches_original_resource = Resource(
        name="caches", device="/dev/drbd0", nodes=cache_original_drbd_nodes
    )
    caches_failover_resource = Resource(
        name="caches", device="/dev/drbd0", nodes=cache_failover_drbd_nodes
    )
    cores_resource = Resource(name="cores", device="/dev/drbd100", nodes=core_drbd_nodes)

    return caches_original_resource, caches_failover_resource, cores_resource


def power_failure(primary_node, data_path):
    with TestRun.use_dut(primary_node), TestRun.step("Make sure drbd instances are in sync"):
        primary_node.cache_drbd.wait_for_sync()
        primary_node.core_drbd.wait_for_sync()

    with TestRun.use_dut(primary_node), TestRun.step(
        "Switch cache to WO, get cache stats and core's md5 and restore WB"
    ):
        primary_node.cache.set_cache_mode(CacheMode.WO)
        core_md5 = TestRun.executor.run(f"md5sum {data_path}").stdout.split()[0]
        cache_stats = primary_node.cache.get_statistics().usage_stats
        primary_node.cache.set_cache_mode(CacheMode.WB)

    with TestRun.use_dut(primary_node), TestRun.step(
        f"Simulate power failure on {primary_node.ip}"
    ):
        power_control = TestRun.plugin_manager.get_plugin("power_control")
        power_control.power_cycle(wait_for_connection=False)

    return core_md5, cache_stats


def failover_sequence(standby_node, drbd_resource, filesystem, core):
    with TestRun.use_dut(standby_node), TestRun.step(f"Stop cache DRBD on the {standby_node.ip}"):
        standby_node.cache_drbd.down()

    with TestRun.use_dut(standby_node), TestRun.step(
        f"Set core DRBD as primary on the {standby_node.ip}"
    ):
        standby_node.core_drbd.set_primary()

    with TestRun.use_dut(standby_node), TestRun.step("Detach the standby cache instance"):
        standby_node.cache.standby_detach()
        TestRun.executor.run_expect_fail(f"ls -la /dev/ | grep {cache_exp_obj_path}")

    with TestRun.use_dut(standby_node), TestRun.step(f"Start primary DRBD on {standby_node.ip}"):
        drbd_resource.save()
        standby_node.cache_drbd = Drbd(drbd_resource)
        standby_node.cache_drbd_dev = standby_node.cache_drbd.up()
        standby_node.cache_drbd.set_primary()

    with TestRun.use_dut(standby_node), TestRun.step(f"Activate cache on {standby_node.ip}"):
        Udev.disable()
        standby_node.cache.standby_activate(standby_node.cache_drbd_dev)
        TestRun.executor.run_expect_success(f"ls -la /dev/ | grep cas{cache_id}-1")

    if filesystem:
        with TestRun.use_dut(standby_node), TestRun.step(f"Mount core"):
            TestRun.executor.run(f"rm -rf {mountpoint}")
            fs_utils.create_directory(path=mountpoint)
            core.mount(mountpoint)


def postfailover_check(new_primary_node, data_path, core_md5, cache_stats):
    with TestRun.use_dut(new_primary_node), TestRun.step(f"Make sure the usage stats are correct"):
        failover_cache_stats = new_primary_node.cache.get_statistics().usage_stats
        if cache_stats.dirty != failover_cache_stats.dirty:
            TestRun.LOGGER.error(
                "The number of dirty blocks after the failover sequence doesn't match\n"
                f"Dirty before the failover {cache_stats.dirty}\n"
                f"Dirty after the failover {failover_cache_stats.dirty}\n"
            )

    with TestRun.use_dut(new_primary_node), TestRun.step(
        f"Swtich cache to WO, make sure md5 of {data_path} is correct and restore WB"
    ):
        new_primary_node.cache.set_cache_mode(CacheMode.WO)
        failover_core_md5 = TestRun.executor.run(f"md5sum {data_path}").stdout.split()[0]
        new_primary_node.cache.set_cache_mode(CacheMode.WB)

        if failover_core_md5 != core_md5:
            TestRun.LOGGER.error("md5 after the failover sequence doesn't match")


def new_failover_instance(new_secondary_node, drbd_resource, *, autoload):
    if autoload:
        with TestRun.use_dut(new_secondary_node), TestRun.step(
            f"Verify whether the passive cache instance on {new_secondary_node.ip}"
            f" started automatically"
        ):
            caches = get_caches()
            if len(caches) < 1:
                TestRun.LOGGER.error(f"Cache not present in system")
            else:
                cache_status = caches[0].get_status()
                if cache_status != CacheStatus.standby:
                    TestRun.LOGGER.error(
                        f'Expected Cache state: "{CacheStatus.standby.value}" '
                        f'Got "{cache_status.value}" instead.'
                    )
    else:
        with TestRun.use_dut(new_secondary_node), TestRun.step(
            f"Zero the standby-cache-to-be device on {new_secondary_node.ip}"
        ):
            dd = Dd().input("/dev/zero").output(new_secondary_node.raid.path)
            dd.run()
            sync()

        with TestRun.use_dut(new_secondary_node), TestRun.step(
            f"Prepare standby cache instance on {new_secondary_node.ip}"
        ):
            new_secondary_node.cache = casadm.standby_init(
                cache_dev=new_secondary_node.raid,
                cache_line_size=str(cls.value.value // 1024),
                cache_id=cache_id,
                force=True,
            )

    with TestRun.use_dut(new_secondary_node), TestRun.step(
        f"Start secondary DRBD on {new_secondary_node.ip}"
        "" if autoload else " with newly created metadata"
    ):
        drbd_resource.save()
        if not autoload:
            new_secondary_node.cache_drbd.create_metadata()
        new_secondary_node.cache_drbd = Drbd(drbd_resource)
        new_secondary_node.cache_drbd_dev = new_secondary_node.cache_drbd.up()
