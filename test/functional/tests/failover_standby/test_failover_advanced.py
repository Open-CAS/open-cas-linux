#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from datetime import timedelta
import os
import pytest
import time

from api.cas import casadm, cli
from api.cas.cache_config import (
    CacheMode,
    CleaningPolicy,
    CacheModeTrait,
    CacheLineSize,
    SeqCutOffPolicy,
    FlushParametersAlru,
    Time,
)
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from storage_devices.drbd import Drbd
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit
from test_utils.filesystem.file import File
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite
from test_tools.fs_utils import readlink, create_directory
from test_utils.drbd import Resource, Node
from test_utils.size import Size, Unit

from test_failover_multihost import check_drbd_installed

cache_size = Size(10, Unit.GibiByte)
metadata_size = Size(1024, Unit.MebiByte)
core_size = Size(15, Unit.GibiByte)
cache_id = 37
cache_exp_obj_path = f"/dev/cas-cache-{cache_id}"


# Calculate random io size (in bytes) to insert (on avarage) all cachelines
# for given cache/core device size, cacheline size and I/O block size.
#
# When inserting to cache randomly with block size < cacheline size it is not
# enough to send single I/O per one cacheline, as some operations will hit
# the same cacheline, leaving some cachelines unused. Increasing number of I/O
# to (cache_capcity_B / io_block_size) would definetely fill the entire cache,
# but would also overfill the cache, resulting in unnecessary eviction (assuming
# core size > cache capacity).
#
# This function calculates just the right amount of I/O to insert exactly the right
# (cache_capacity_b / cls) amount of cachelines (statistically). Due to random fluctuations
# cache occupancy might be slightly smaller or a slight overfill might occur - resulting
# in eviction at the end of fill process.
def calc_io_size(cache_size, core_size, cache_line_size, block_size):
    target_occupancy = 1.0  # increase to avoid underfill due to random I/O fluctuations
    bs = block_size.value
    dev_ratio = cache_size.value / core_size.value
    bs_ratio = block_size.value / int(cache_line_size)
    size = core_size.value * (1 - (1 - target_occupancy * dev_ratio) ** (bs_ratio))
    return Size(int(size) // bs * bs, Unit.Byte)


def timed_async_power_cycle():
    start = time.time()
    power_control = TestRun.plugin_manager.get_plugin("power_control")
    power_control.power_cycle(wait_for_connection=False)
    end = time.time()

    if end - start > 5:
        TestRun.LOGGER.warning(
            f"Power cycle request took {end - start} seconds, this could result in test failure "
            "due to insufficient dirty data after failover."
        )


@pytest.mark.require_disk("cache_dev", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", [c for c in CleaningPolicy if c != CleaningPolicy.nop])
@pytest.mark.parametrize("num_iterations", [2])
def test_failover_during_background_cleaning(cache_mode, cls, cleaning_policy, num_iterations):
    """
    title: Failover sequence with background cleaning:
    description:
      Verify proper failover behaviour and data integrity after power failure during background
      cleaning running.
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes with lazy writes - to make sure dirty data is produced so that
        metadata synchronization between hosts occurs
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy - as different policies have separate metadata handling implementation
    steps:
      - On 2 DUTs (main and backup) prepare cache device of 10GiB size
      - On 2 DUTs (main and backup) prepare primary storage device of size 15GiB
      - On main DUT prefill primary storage device with zeroes
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start cache on top of cache DRBD device with parametrized cacheline size and cache mode
          - Set cleaning policy to NOP
          - Set sequential cutoff to never
          - Wait for DRBD synchronization
          - Fill cache with random 50% read/write mix workload, block size 4K
          - Verify cache is > 25% dirty
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to the parametrized cache mode without flush
          - Switch to parametrized cleaning policy
          - Wait for the background cleaner to start working (no wait for ACP, according to
            policy parameters for ALRU)
          - Verify cleaner is progressing by inspecting dirty statistics
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache drive
          - verify dirty stats did not increase
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        cache_drbd_resource, core_drbd_resource = create_drbd_configs(primary_node, secondary_node)

    for i in TestRun.iteration(range(num_iterations)):
        with TestRun.step("Prefill primary storage device with zeroes"), TestRun.use_dut(
            primary_node
        ):
            Dd().block_size(Size(1, Unit.MebiByte)).input("/dev/zero").output(
                f"{primary_node.core_dev.path}"
            ).oflag("direct").run()

        with TestRun.step("Start standby cache instance on secondary DUT"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache = casadm.standby_init(
                cache_dev=secondary_node.cache_dev,
                cache_line_size=cls,
                cache_id=cache_id,
                force=True,
            )

        for dut in TestRun.duts:
            with TestRun.step(f"Create DRBD instances on {dut.ip}"), TestRun.use_dut(dut):
                dut.cache_drbd = Drbd(cache_drbd_resource)
                dut.cache_drbd.create_metadata(force=True)
                dut.cache_drbd_dev = dut.cache_drbd.up()

                dut.core_drbd = Drbd(core_drbd_resource)
                dut.core_drbd.create_metadata(force=True)
                dut.core_drbd_dev = dut.core_drbd.up()

        with TestRun.step(
            f"Set {primary_node.ip} as primary node for both DRBD instances"
        ), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.set_primary()
            primary_node.core_drbd.set_primary()

        with TestRun.step(
            f"Start cache on top of cache DRBD device with cacheline size {cls} and {cache_mode} "
            "cache mode"
        ), TestRun.use_dut(primary_node):
            primary_node.cache = casadm.start_cache(
                primary_node.cache_drbd_dev,
                force=True,
                cache_mode=cache_mode,
                cache_line_size=cls,
                cache_id=cache_id,
            )

            core = primary_node.cache.add_core(primary_node.core_drbd_dev)

        with TestRun.step("Set NOP cleaning policy"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step("Disable sequential cutoff"), TestRun.use_dut(primary_node):
            primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Wait for DRBD synchronization"), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.wait_for_sync()
            primary_node.core_drbd.wait_for_sync()

        with TestRun.step(
            "Fill cache with random 50% read/write mix workload, block size 4K"
        ), TestRun.use_dut(primary_node):
            bs = Size(4, Unit.KibiByte)
            io_size = calc_io_size(cache_size, core_size, cls, bs)

            if CacheModeTrait.InsertRead not in CacheMode.get_traits(cache_mode):
                io_size = io_size * 2

            fio = (
                Fio()
                .create_command()
                .direct(True)
                .read_write(ReadWrite.randrw)
                .io_depth(64)
                .block_size(bs)
                .size(core_size)
                .io_size(io_size)
                .file_name(core.path)
            )
            fio.run()

        with TestRun.step("Verify cache is > 25% dirty"), TestRun.use_dut(primary_node):
            dirty_after_initial_io = primary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            if dirty_after_initial_io < 25:
                if dirty_after_initial_io == 0.0:
                    TestRun.LOGGER.exception("Expected at least 25% dirty data, got 0")
                else:
                    TestRun.LOGGER.warning(
                        f"Expected at least 25% dirty data, got {dirty_after_initial_io}"
                    )

        with TestRun.step("Switch to WO cache mode without flush"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(CacheMode.WO, flush=False)

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            primary_node
        ):
            checksum1 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step(
            f"Switch back to the {cache_mode} cache mode without flush"
        ), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(cache_mode, flush=False)

        with TestRun.step(f"Switch to {cleaning_policy} cleaning policy"), TestRun.use_dut(
            primary_node
        ):
            primary_node.cache.set_cleaning_policy(cleaning_policy)

            if cleaning_policy == CleaningPolicy.alru:
                TestRun.LOGGER.info("Configure ALRU to trigger immediately\n")
                params = FlushParametersAlru(
                    activity_threshold=Time(milliseconds=0),
                    wake_up_time=Time(seconds=0),
                    staleness_time=Time(seconds=1),
                )
                primary_node.cache.set_params_alru(params)

        with TestRun.step("Wait 2s"):
            time.sleep(2)

        with TestRun.step(
            "Verify cleaner is progressing by inspecting dirty statistics"
        ), TestRun.use_dut(primary_node):
            dirty_after_cleaning = primary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            TestRun.LOGGER.info(
                f"Dirty stats change: {dirty_after_initial_io}% -> {dirty_after_cleaning}%"
            )

            # make sure there is cleaning progress
            if dirty_after_cleaning >= dirty_after_initial_io:
                TestRun.LOGGER.exception("No cleaning progress detected")

            # make sure there is dirty data left to clean
            if dirty_after_cleaning < 20:
                TestRun.LOGGER.exception("Not enough dirty data")

        with TestRun.step(f"Power off the main DUT"), TestRun.use_dut(primary_node):
            timed_async_power_cycle()

        with TestRun.step("Stop cache DRBD on the secondary node"), TestRun.use_dut(secondary_node):
            secondary_node.cache_drbd.down()

        with TestRun.step("Set backup DUT as primary for core DRBD"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.core_drbd.set_primary()

        with TestRun.step("Deatch cache drive from standby cache instance"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache.standby_detach()

        with TestRun.step(
            "Activate standby cache instance directly on the cache drive"
        ), TestRun.use_dut(secondary_node):
            secondary_node.cache.standby_activate(secondary_node.cache_dev)

        with TestRun.step("Verify there is some dirty data after failover"), TestRun.use_dut(
            secondary_node
        ):
            dirty_after_failover = secondary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            if dirty_after_failover > dirty_after_cleaning:
                TestRun.LOGGER.exception("Unexpeted increase in dirty cacheline count")
            elif dirty_after_failover == 0:
                TestRun.LOGGER.exception(
                    "No dirty data after failover. This might indicate that power cycle took too "
                    "long or cleaning/network is too fast\n"
                )
            else:
                TestRun.LOGGER.info(f"Dirty cachelines after failover: {dirty_after_failover}")

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            secondary_node
        ):
            checksum2 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step("Verify that the two checksums are equal"):
            if checksum1 != checksum2:
                TestRun.LOGGER.error(
                    f"Checksum mismatch: primary {checksum1} secondary {checksum2}"
                )

        with TestRun.step("Cleanup after iteration"), TestRun.use_dut(secondary_node):
            secondary_node.cache.stop(no_data_flush=True)
            Drbd.down_all()

        with TestRun.step("Wait for the primary DUT to be back online"), TestRun.use_dut(
            primary_node
        ):
            TestRun.executor.wait_for_connection()


@pytest.mark.require_disk("cache_dev", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("num_iterations", [2])
def test_failover_during_dirty_flush(cache_mode, cls, num_iterations):
    """
    title: Failover sequence with after power failure during dirty data flush
    description:
      Verify proper failover behaviour and data integrity after power failure during
      user-issued cleaning
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes with lazy writes - to make sure dirty data is produced so that
        metadata synchronization between hosts occurs
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
    steps:
      - On 2 DUTs (main and backup) prepare cache device of 10GiB size
      - On 2 DUTs (main and backup) prepare primary storage device of size 15GiB
      - On main DUT prefill primary storage device with zeroes
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start cache on top of cache DRBD device with parametrized cacheline size and cache mode
          - Wait for DRBD synchronization
          - Set cleaning policy to NOP
          - Set sequential cutoff to never
          - Fill cache with random 50% read/write mix workload, block size 4K
          - Verify cache is > 25% dirty
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to the parametrized cache mode without flush
          - Issue cache flush command
          - Verify flush is progressing by inspecting dirty statistics
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache drive
          - verify dirty stats did not increase
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        cache_drbd_resource, core_drbd_resource = create_drbd_configs(primary_node, secondary_node)

    for i in TestRun.iteration(range(num_iterations)):
        with TestRun.step("Prefill primary storage device with zeroes"), TestRun.use_dut(
            primary_node
        ):
            Dd().block_size(Size(1, Unit.MebiByte)).input("/dev/zero").output(
                f"{primary_node.core_dev.path}"
            ).oflag("direct").run()

        with TestRun.step("Start standby cache instance on secondary DUT"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache = casadm.standby_init(
                cache_dev=secondary_node.cache_dev,
                cache_line_size=cls,
                cache_id=cache_id,
                force=True,
            )

        for dut in TestRun.duts:
            with TestRun.step(f"Create DRBD instances on {dut.ip}"), TestRun.use_dut(dut):
                dut.cache_drbd = Drbd(cache_drbd_resource)
                dut.cache_drbd.create_metadata(force=True)
                dut.cache_drbd_dev = dut.cache_drbd.up()

                dut.core_drbd = Drbd(core_drbd_resource)
                dut.core_drbd.create_metadata(force=True)
                dut.core_drbd_dev = dut.core_drbd.up()

        with TestRun.step(
            f"Set {primary_node.ip} as primary node for both DRBD instances"
        ), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.set_primary()
            primary_node.core_drbd.set_primary()

        with TestRun.step(
            f"Start cache on top of cache DRBD device with cacheline size {cls} and {cache_mode} "
            "cache mode"
        ), TestRun.use_dut(primary_node):
            primary_node.cache = casadm.start_cache(
                primary_node.cache_drbd_dev,
                force=True,
                cache_mode=cache_mode,
                cache_line_size=cls,
                cache_id=cache_id,
            )

            core = primary_node.cache.add_core(primary_node.core_drbd_dev)

        with TestRun.step("Set NOP cleaning policy"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step("Disable sequential cutoff"), TestRun.use_dut(primary_node):
            primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Wait for DRBD synchronization"), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.wait_for_sync()
            primary_node.core_drbd.wait_for_sync()

        with TestRun.step(
            "Fill cache with random 50% read/write mix workload, block size 4K"
        ), TestRun.use_dut(primary_node):
            bs = Size(4, Unit.KibiByte)
            io_size = calc_io_size(cache_size, core_size, cls, bs)

            if CacheModeTrait.InsertRead not in CacheMode.get_traits(cache_mode):
                io_size = io_size * 2

            fio = (
                Fio()
                .create_command()
                .direct(True)
                .read_write(ReadWrite.randrw)
                .block_size(bs)
                .size(core_size)
                .io_size(io_size)
                .file_name(core.path)
                .io_depth(64)
                .rand_seed(TestRun.random_seed)
                .set_param("allrandrepeat", 1)
                .set_flags("refill_buffers")
            )
            fio.run()

        with TestRun.step("Verify cache is > 25% dirty"), TestRun.use_dut(primary_node):
            dirty_after_initial_io = primary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            if dirty_after_initial_io < 25:
                if dirty_after_initial_io == 0.0:
                    TestRun.LOGGER.exception("Expected at least 25% dirty data, got 0")
                else:
                    TestRun.LOGGER.warning(
                        f"Expected at least 25% dirty data, got {dirty_after_initial_io}"
                    )

        with TestRun.step("Switch to WO cache mode without flush"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(CacheMode.WO, flush=False)

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            primary_node
        ):
            checksum1 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step(
            f"Switch back to the {cache_mode} cache mode without flush"
        ), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(cache_mode, flush=False)

        with TestRun.step("Issue cache flush command in background"), TestRun.use_dut(primary_node):
            TestRun.executor.run_in_background(
                cli.flush_cache_cmd(str(primary_node.cache.cache_id))
            )

        with TestRun.step("Wait 2s"):
            time.sleep(2)

        with TestRun.step(
            "Verify cleaner is progressing by inspecting dirty statistics"
        ), TestRun.use_dut(primary_node):
            dirty_after_cleaning = primary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            TestRun.LOGGER.info(
                f"Dirty stats change: {dirty_after_initial_io}% -> {dirty_after_cleaning}%"
            )

            # make sure there is cleaning progress
            if dirty_after_cleaning >= dirty_after_initial_io:
                TestRun.LOGGER.exception("No cleaning progress detected")

            # make sure there is dirty data left to clean
            if dirty_after_cleaning < 20:
                TestRun.LOGGER.exception("Not enough dirty data")

        with TestRun.step(f"Power off the main DUT"), TestRun.use_dut(primary_node):
            timed_async_power_cycle()

        with TestRun.step("Stop cache DRBD on the secondary node"), TestRun.use_dut(secondary_node):
            secondary_node.cache_drbd.down()

        with TestRun.step("Set backup DUT as primary for core DRBD"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.core_drbd.set_primary()

        with TestRun.step("Deatch cache drive from standby cache instance"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache.standby_detach()

        with TestRun.step(
            "Activate standby cache instance directly on the cache drive"
        ), TestRun.use_dut(secondary_node):
            secondary_node.cache.standby_activate(secondary_node.cache_dev)

        with TestRun.step("Verify there is some dirty data after failover"), TestRun.use_dut(
            secondary_node
        ):
            dirty_after_failover = secondary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            if dirty_after_failover > dirty_after_cleaning:
                TestRun.LOGGER.exception("Unexpeted increase in dirty cacheline count")
            elif dirty_after_failover == 0:
                TestRun.LOGGER.exception(
                    "No dirty data after failover. This might indicate that power cycle took too "
                    "long or cleaning/network is too fast\n"
                )
            else:
                TestRun.LOGGER.info(f"Dirty cachelines after failover: {dirty_after_failover}")

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            secondary_node
        ):
            checksum2 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step("Verify that the two checksums are equal"):
            if checksum1 != checksum2:
                TestRun.LOGGER.error(
                    f"Checksum mismatch: primary {checksum1} secondary {checksum2}"
                )

        with TestRun.step("Cleanup after iteration"), TestRun.use_dut(secondary_node):
            secondary_node.cache.stop(no_data_flush=True)
            Drbd.down_all()

        with TestRun.step("Wait for the primary DUT to be back online"), TestRun.use_dut(
            primary_node
        ):
            TestRun.executor.wait_for_connection()


@pytest.mark.require_disk("cache_dev", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cache_mode", CacheMode.with_any_trait(CacheModeTrait.InsertRead))
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrize("num_iterations", [2])
def test_failover_during_io_with_eviction(cache_mode, cls, cleaning_policy, num_iterations):
    """
    title: Failover sequence with after power failure during I/O with eviction
    description:
      Verify proper failover behaviour and data integrity after power failure during
      I/O handling with eviction
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes that insert reads to trigger eviction during read I/O
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy: all policies - ALRU configured to trigger immediately
    steps:
      - On 2 DUTs (main and backup) prepare cache device of 10GiB size
      - On 2 DUTs (main and backup) prepare primary storage device of size 15GiB
      - On main DUT prefill primary storage device with zeroes
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start WB cache on top of cache DRBD device with parametrized cacheline size
          - Set cleaning policy to NOP
          - Set sequential cutoff to never
          - Wait for DRBD synchronization
          - Fill cache with random 50% read/write mix workload, block size = parametrized cache
            line size
          - Verify cache is > 25% dirty
          - Verify cache ocuppancy is 100%
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to parametrized cache mode without flush
          - Switch to parametrized cleaning policy and cache mode
          - Run multi-threaded I/O, 100% random read, block_size range [4K, parametrized cache line
            size] with 4K increment, different random seed than the previous prefill I/O, entire
            primary storage LBA address range, runtime 1h
          - Verify cache miss statistic is being incremented
          - Verify pass-through I/O statistic is not being incremented
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache drive
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        cache_drbd_resource, core_drbd_resource = create_drbd_configs(primary_node, secondary_node)

    for i in TestRun.iteration(range(num_iterations)):
        with TestRun.step("Prefill primary storage device with zeroes"), TestRun.use_dut(
            primary_node
        ):
            Dd().block_size(Size(1, Unit.MebiByte)).input("/dev/zero").output(
                f"{primary_node.core_dev.path}"
            ).oflag("direct").run()

        with TestRun.step("Start standby cache instance on secondary DUT"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache = casadm.standby_init(
                cache_dev=secondary_node.cache_dev,
                cache_line_size=cls,
                cache_id=cache_id,
                force=True,
            )

        for dut in TestRun.duts:
            with TestRun.step(f"Create DRBD instances on {dut.ip}"), TestRun.use_dut(dut):
                dut.cache_drbd = Drbd(cache_drbd_resource)
                dut.cache_drbd.create_metadata(force=True)
                dut.cache_drbd_dev = dut.cache_drbd.up()

                dut.core_drbd = Drbd(core_drbd_resource)
                dut.core_drbd.create_metadata(force=True)
                dut.core_drbd_dev = dut.core_drbd.up()

        with TestRun.step(
            f"Set {primary_node.ip} as primary node for both DRBD instances"
        ), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.set_primary()
            primary_node.core_drbd.set_primary()

        with TestRun.step(
            f"Start cache on top of cache DRBD device with cacheline size {cls} and WB cache mode"
        ), TestRun.use_dut(primary_node):
            primary_node.cache = casadm.start_cache(
                primary_node.cache_drbd_dev,
                force=True,
                cache_mode=CacheMode.WB,
                cache_line_size=cls,
                cache_id=cache_id,
            )

            core = primary_node.cache.add_core(primary_node.core_drbd_dev)

        with TestRun.step("Set NOP cleaning policy"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step("Disable sequential cutoff"), TestRun.use_dut(primary_node):
            primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Wait for DRBD synchronization"), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.wait_for_sync()
            primary_node.core_drbd.wait_for_sync()

        with TestRun.step(
            f"Fill cache with random 50% read/write mix workload, block size {int(cls)//1024}KiB"
        ), TestRun.use_dut(primary_node):
            bs = Size(int(cls), Unit.Byte)
            io_size = calc_io_size(cache_size, core_size, cls, bs)

            fio = (
                Fio()
                .create_command()
                .direct(True)
                .read_write(ReadWrite.randrw)
                .io_depth(64)
                .block_size(Size(int(cls), Unit.Byte))
                .size(core_size)
                .io_size(io_size)
                .file_name(core.path)
                .rand_seed(TestRun.random_seed)
                .set_param("allrandrepeat", 1)
                .set_flags("refill_buffers")
            )
            fio.run()

        with TestRun.step("Verify cache is > 25% dirty"), TestRun.use_dut(primary_node):
            dirty_after_initial_io = primary_node.cache.get_statistics(
                percentage_val=True
            ).usage_stats.dirty
            if dirty_after_initial_io < 25:
                TestRun.LOGGER.warning("Expected at least 25% dirty data")

        with TestRun.step("Verify cache ocuppancy is 100%"), TestRun.use_dut(primary_node):
            occupancy = primary_node.cache.get_statistics(percentage_val=True).usage_stats.occupancy
            if occupancy < 99:
                TestRun.LOGGER.warning("Expeted cache occupancy close to 100%\n")

        with TestRun.step("Switch to WO cache mode without flush"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(CacheMode.WO, flush=False)

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            primary_node
        ):
            checksum1 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step(f"Set {cache_mode} cache mode without flush"), TestRun.use_dut(
            primary_node
        ):
            primary_node.cache.set_cache_mode(cache_mode, flush=False)

        with TestRun.step(f"Switch to {cleaning_policy} cleaning policy"), TestRun.use_dut(
            primary_node
        ):
            primary_node.cache.set_cleaning_policy(cleaning_policy)

            if cleaning_policy == CleaningPolicy.alru:
                TestRun.LOGGER.info("Configure ALRU to trigger immediately\n")
                params = FlushParametersAlru(
                    activity_threshold=Time(milliseconds=0),
                    wake_up_time=Time(seconds=0),
                    staleness_time=Time(seconds=1),
                )
                primary_node.cache.set_params_alru(params)

        with TestRun.step("Wait 2s for cleaner to kick in"):
            time.sleep(2)

        with TestRun.step("Read stats before fio"), TestRun.use_dut(primary_node):
            stats_before = primary_node.cache.get_statistics()

        with TestRun.step("Run multi-threaded fio"), TestRun.use_dut(primary_node):
            start_size = Size(4, Unit.KibiByte).get_value()
            stop_size = int(cls)

            fio = (
                Fio()
                .create_command()
                .direct(True)
                .read_write(ReadWrite.randread)
                .blocksize_range([(start_size, stop_size)])
                .file_name(core.path)
                .rand_seed(TestRun.random_seed + 1)
                .num_jobs(16)
                .size(core_size)
                .time_based(True)
                .run_time(timedelta(minutes=60))
                .set_param("allrandrepeat", 1)
                .set_flags("refill_buffers")
            )

            fio.run_in_background()

        with TestRun.step("Wait 2s for I/O to take effect"):
            time.sleep(2)

        with TestRun.step("Verify cache miss statistic is being incremented"), TestRun.use_dut(
            primary_node
        ):
            stats_after = primary_node.cache.get_statistics()

            read_misses_before = (
                stats_before.request_stats.read.full_misses
                + stats_before.request_stats.read.part_misses
            )

            read_misses_after = (
                stats_after.request_stats.read.full_misses
                + stats_after.request_stats.read.part_misses
            )

            TestRun.LOGGER.info(f"Read miss change: {read_misses_before} -> {read_misses_after}")

            if read_misses_after <= read_misses_before:
                TestRun.LOGGER.exception(f"Expected read misses increase was not registered")

        with TestRun.step(
            "Verify pass-through I/O statistic is not being incremented"
        ), TestRun.use_dut(primary_node):
            pt_reads_before = stats_before.request_stats.pass_through_reads
            pt_reads_after = stats_after.request_stats.pass_through_reads

            TestRun.LOGGER.info(f"PT reads requests change: {pt_reads_before} -> {pt_reads_after}")

            if pt_reads_before != pt_reads_after:
                TestRun.LOGGER.exception(f"Unexpected increase in PT statistics")

        with TestRun.step(f"Power off the main DUT"), TestRun.use_dut(primary_node):
            timed_async_power_cycle()

        with TestRun.step("Stop cache DRBD on the secondary node"), TestRun.use_dut(secondary_node):
            secondary_node.cache_drbd.down()

        with TestRun.step("Set backup DUT as primary for core DRBD"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.core_drbd.set_primary()

        with TestRun.step("Deatch cache drive from standby cache instance"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache.standby_detach()

        with TestRun.step(
            "Activate standby cache instance directly on the cache drive"
        ), TestRun.use_dut(secondary_node):
            secondary_node.cache.standby_activate(secondary_node.cache_dev)

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            secondary_node
        ):
            checksum2 = TestRun.executor.run(f"md5sum {core.path}").stdout.split()[0]

        with TestRun.step("Verify that the two checksums are equal"):
            if checksum1 != checksum2:
                TestRun.LOGGER.error(
                    f"Checksum mismatch: primary {checksum1} secondary {checksum2}"
                )

        with TestRun.step("Cleanup after iteration"), TestRun.use_dut(secondary_node):
            secondary_node.cache.stop(no_data_flush=True)
            Drbd.down_all()

        with TestRun.step("Wait for the primary DUT to be back online"), TestRun.use_dut(
            primary_node
        ):
            TestRun.executor.wait_for_connection()


@pytest.mark.require_disk("cache_dev", DiskTypeSet([DiskType.optane]))
@pytest.mark.require_disk("core_dev", DiskTypeSet([DiskType.nand]))
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", [c for c in CleaningPolicy if c != CleaningPolicy.alru])
@pytest.mark.parametrize("num_iterations", [1])
def test_failover_io_long(cls, cleaning_policy, num_iterations):
    """
    title:
        Failover WB I/O long
    Description:
         4h I/O with data verification in failover setup
    pass_criteria:
      - Data integrity is maintained
      - Failover procedure success
    parametrizations:
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy: all except ALRU, as it doesn't do any cleaning in runtime
    steps:
      - On 2 DUTs (main and backup) prepare cache device of 10GiB size
      - On 2 DUTs (main and backup) prepare primary storage device of size 15GiB
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start WB cache on top of cache DRBD device with parametrized cacheline size
          - Set the parametrized cleaning policy
          - Set sequential cutoff to never
          - Create XFS file system on CAS exported object
          - Mount file system
          - Preallocate fio file in PT cache mode
          - Wait for DRBD synchronization
          - Run 4h FIO with data verification: random R/W, 16 jobs, filesystem, entire primary
            storage LBA address range, --bssplit=4k/10:8k/25:16k/25:32k/20:64k/10:128k/5:256k/5
          - Verify no data errors
          - Switch to WO cache mode without flush
          - Calculate checksum of fio test file(s)
          - Switch back to WB cache mode without flush
          - Flush page cache
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache drive
          - mount file system located on CAS exported object
          - Calculate checksum of fio test file(s)
       - Verify checksums from the previous steps are equal
       - Power on the main DUT
    """
    with TestRun.step("Make sure DRBD is installed on both nodes"):
        check_drbd_installed(TestRun.duts)

    with TestRun.step("Prepare DUTs"):
        prepare_devices(TestRun.duts)
        primary_node, secondary_node = TestRun.duts

    with TestRun.step(f"Create mount point"):
        mountpoint = "/tmp/standby_io_test_mount_point"
        for dut in TestRun.duts:
            with TestRun.use_dut(secondary_node):
                TestRun.executor.run(f"rm -rf {mountpoint}")
                create_directory(path=mountpoint)

    with TestRun.step("Prepare DRBD config files on both DUTs"):
        cache_drbd_resource, core_drbd_resource = create_drbd_configs(primary_node, secondary_node)

    for i in TestRun.iteration(range(num_iterations)):
        with TestRun.step("Prefill primary storage device with zeroes"), TestRun.use_dut(
            primary_node
        ):
            Dd().block_size(Size(1, Unit.MebiByte)).input("/dev/zero").output(
                f"{primary_node.core_dev.path}"
            ).oflag("direct").run()

        with TestRun.step("Start standby cache instance on secondary DUT"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache = casadm.standby_init(
                cache_dev=secondary_node.cache_dev,
                cache_line_size=cls,
                cache_id=cache_id,
                force=True,
            )

        for dut in TestRun.duts:
            with TestRun.step(f"Create DRBD instances on {dut.ip}"), TestRun.use_dut(dut):
                dut.cache_drbd = Drbd(cache_drbd_resource)
                dut.cache_drbd.create_metadata(force=True)
                dut.cache_drbd_dev = dut.cache_drbd.up()

                dut.core_drbd = Drbd(core_drbd_resource)
                dut.core_drbd.create_metadata(force=True)
                dut.core_drbd_dev = dut.core_drbd.up()

        with TestRun.step(
            f"Set {primary_node.ip} as primary node for both DRBD instances"
        ), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.set_primary()
            primary_node.core_drbd.set_primary()

        with TestRun.step(
            f"Start cache on top of cache DRBD device with cacheline size {cls} and WB cache mode"
        ), TestRun.use_dut(primary_node):
            primary_node.cache = casadm.start_cache(
                primary_node.cache_drbd_dev,
                force=True,
                cache_mode=CacheMode.WB,
                cache_line_size=cls,
                cache_id=cache_id,
            )

            core = primary_node.cache.add_core(primary_node.core_drbd_dev)

        with TestRun.step(f"Set {cleaning_policy} cleaning policy"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cleaning_policy(cleaning_policy)

        with TestRun.step("Disable sequential cutoff"), TestRun.use_dut(primary_node):
            primary_node.cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)

        with TestRun.step("Create XFS file system on CAS exported object"), TestRun.use_dut(
            primary_node
        ):
            core.create_filesystem(Filesystem.xfs)

        with TestRun.step(f"Mount file system"), TestRun.use_dut(primary_node):
            core.mount(mountpoint)

        with TestRun.step("Prepare fio command"), TestRun.use_dut(primary_node):
            file_path = mountpoint + os.path.sep + "fio_file"
            fio = (
                Fio()
                .create_command()
                .direct(True)
                .read_write(ReadWrite.randrw)
                .bs_split("4k/10:8k/25:16k/25:32k/20:64k/10:128k/5:256k/5")
                .file_name(file_path)
                .rand_seed(TestRun.random_seed)
                .num_jobs(16)
                .size(core_size * 0.9)  # leave some room for FS metadata
                .io_size(Size(0, Unit.Byte))
                .do_verify(True)
                .set_param("allrandrepeat", 1)
                .set_flags("refill_buffers")
            )

        with TestRun.step("Preallocate fio file in pass-through"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(CacheMode.PT, flush=False)
            # 0 bytes of actual I/O, *not* time based - will just allocate the file
            fio.time_based(False).run(timedelta(hours=1))
            primary_node.cache.set_cache_mode(CacheMode.WB, flush=False)

        with TestRun.step("Wait for DRBD synchronization"), TestRun.use_dut(primary_node):
            primary_node.cache_drbd.wait_for_sync()
            primary_node.core_drbd.wait_for_sync()

        with TestRun.step(
            "Run 4h FIO with data verification: random R/W, 16 jobs, filesystem, "
            "entire primary storage LBA address range, block size split "
            "4k/10:8k/25:16k/25:32k/20:64k/10:128k/5:256k/5"
        ), TestRun.use_dut(primary_node):
            fio.time_based(True).run_time(timedelta(hours=4)).run()

        with TestRun.step("Switch to WO cache mode without flush"), TestRun.use_dut(primary_node):
            primary_node.cache.set_cache_mode(CacheMode.WO, flush=False)

        with TestRun.step("Calculate checksum of fio test file(s)"), TestRun.use_dut(primary_node):
            checksum1 = File(file_path).md5sum()

        with TestRun.step(f"Switch back to the WB cache mode without flush"), TestRun.use_dut(
            primary_node
        ):
            primary_node.cache.set_cache_mode(CacheMode.WB, flush=False)

        with TestRun.step(f"Power off the main DUT"), TestRun.use_dut(primary_node):
            power_control = TestRun.plugin_manager.get_plugin("power_control")
            power_control.power_cycle(wait_for_connection=False)

        with TestRun.step("Stop cache DRBD on the secondary node"), TestRun.use_dut(secondary_node):
            secondary_node.cache_drbd.down()

        with TestRun.step("Set backup DUT as primary for core DRBD"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.core_drbd.set_primary()

        with TestRun.step("Deatch cache drive from standby cache instance"), TestRun.use_dut(
            secondary_node
        ):
            secondary_node.cache.standby_detach()

        with TestRun.step(
            "Activate standby cache instance directly on the cache drive"
        ), TestRun.use_dut(secondary_node):
            secondary_node.cache.standby_activate(secondary_node.cache_dev)

        with TestRun.step(f"Mount file system"), TestRun.use_dut(secondary_node):
            core.mount(mountpoint)

        with TestRun.step("Calculate checksum of CAS exported object"), TestRun.use_dut(
            secondary_node
        ):
            checksum2 = File(file_path).md5sum()

        with TestRun.step("Verify that the two checksums are equal"):
            if checksum1 != checksum2:
                TestRun.LOGGER.error(
                    f"Checksum mismatch: primary {checksum1} secondary {checksum2}"
                )

        with TestRun.step("Cleanup after iteration"), TestRun.use_dut(secondary_node):
            core.unmount()
            secondary_node.cache.stop(no_data_flush=True)
            Drbd.down_all()

        with TestRun.step("Wait for the primary DUT to be back online"), TestRun.use_dut(
            primary_node
        ):
            TestRun.executor.wait_for_connection()


def check_drbd_installed(duts):
    for dut in duts:
        with TestRun.use_dut(dut):
            if not Drbd.is_installed():
                TestRun.fail(f"DRBD is not installed on DUT {dut.ip}")


def prepare_devices(duts):
    for dut in duts:
        with TestRun.use_dut(dut):
            TestRun.dut.hostname = TestRun.executor.run_expect_success("uname -n").stdout

            TestRun.disks["cache_dev"].create_partitions([cache_size] + [metadata_size] * 2)
            dut.cache_dev = TestRun.disks["cache_dev"].partitions[0]
            dut.cache_md_dev = TestRun.disks["cache_dev"].partitions[1]
            dut.core_md_dev = TestRun.disks["cache_dev"].partitions[2]

            TestRun.disks["core_dev"].create_partitions([core_size])
            dut.core_dev = TestRun.disks["core_dev"].partitions[0]


def create_drbd_configs(primary, secondary):
    cache_drbd_nodes = [
        Node(
            primary.hostname, primary.cache_dev.path, primary.cache_md_dev.path, primary.ip, "7790"
        ),
        Node(
            secondary.hostname,
            cache_exp_obj_path,
            secondary.cache_md_dev.path,
            secondary.ip,
            "7790",
        ),
    ]
    core_drbd_nodes = [
        Node(dut.hostname, dut.core_dev.path, dut.core_md_dev.path, dut.ip, "7791")
        for dut in [primary, secondary]
    ]

    cache_drbd_resource = Resource(name="caches", device="/dev/drbd0", nodes=cache_drbd_nodes)
    core_drbd_resource = Resource(name="cores", device="/dev/drbd100", nodes=core_drbd_nodes)

    for dut in [primary, secondary]:
        with TestRun.use_dut(dut):
            cache_drbd_resource.save()
            core_drbd_resource.save()

    return cache_drbd_resource, core_drbd_resource
