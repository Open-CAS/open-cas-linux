#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from time import sleep

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait
from api.cas.casadm import StatsFilter
from api.cas.statistics import get_stats_dict, get_stat_value
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_tools.udev import Udev
from type_def.size import Size, Unit

cores_per_cache = 4
cache_size = Size(20, Unit.GibiByte)
core_size = Size(10, Unit.GibiByte)
io_value = 1000
io_size = Size(io_value, Unit.Blocks4096)
# Offset fio past the area the kernel partition scan touches, so that
# scan-inserted and IO-inserted cache lines never overlap.
fio_offset = Size(1, Unit.MebiByte)
# The kernel reads ~3 × 4 KiB blocks from each exported object right
# after the core is added (and again after a cache reload).
scan_count = 3
scan_size = Size(scan_count, Unit.Blocks4096)
stat_filter = [StatsFilter.usage, StatsFilter.req, StatsFilter.blk]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
def test_stats_values(cache_mode):
    """
        title: Check for proper statistics values.
        description: |
          Check if CAS displays proper usage, request, block and error statistics values
          for core devices - at the start (after partition scan), after IO and after cache
          reload. Also check if cores' statistics match cache's statistics.
        pass_criteria:
          - Usage, request, block and error statistics have proper values.
          - Cores' statistics match cache's statistics.
    """

    inserts_reads = cache_mode in CacheMode.with_traits(CacheModeTrait.InsertRead)
    inserts_writes = cache_mode in CacheMode.with_traits(CacheModeTrait.InsertWrite)
    lazy_writes = cache_mode in CacheMode.with_traits(CacheModeTrait.LazyWrites)
    # PT is the only mode that truly passes reads through; all other modes
    # process scan reads as read full misses (serviced), even if they don't
    # insert the data (WO).
    pass_through = cache_mode == CacheMode.PT

    with TestRun.step("Partition cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([cache_size])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([core_size] * cores_per_cache)

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Start cache in {cache_mode} mode and add {cores_per_cache} cores"):
        cache = casadm.start_cache(cache_dev.partitions[0], cache_mode, force=True)
        cores = [cache.add_core(core_dev.partitions[j]) for j in range(cores_per_cache)]

    # -- Initial statistics (partition scan only) -------------------------

    with TestRun.step("Check initial usage statistics (partition scan effects)"):
        # InsertRead modes cache the scan blocks as clean data;
        # other modes pass the reads through — nothing is cached.
        expected_occupancy = scan_size.value if inserts_reads else 0
        expected_free = cache.size.value - expected_occupancy * cores_per_cache
        expected_clean = expected_occupancy
        expected_occupancy_perc = round(100 * expected_occupancy / cache.size.value, 1)
        expected_free_perc = round(100 * expected_free / cache.size.value, 1)
        expected_clean_perc = 100 if inserts_reads else 0

        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}) initial: "

            usage_checks = [
                ("occupancy", stats.usage_stats.occupancy.value,
                 stats_perc.usage_stats.occupancy,
                 expected_occupancy, expected_occupancy_perc),
                ("free", stats.usage_stats.free.value,
                 stats_perc.usage_stats.free,
                 expected_free, expected_free_perc),
                ("clean", stats.usage_stats.clean.value,
                 stats_perc.usage_stats.clean,
                 expected_clean, expected_clean_perc),
                ("dirty", stats.usage_stats.dirty.value,
                 stats_perc.usage_stats.dirty, 0, 0),
            ]
            for name, val, val_perc, exp, exp_perc in usage_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}{name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(f"{msg}{name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check initial request statistics (partition scan effects)"):
        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}) initial: "

            # Only PT passes scan reads through; all other modes process
            # them as read full misses (serviced), even without InsertRead.
            expected_read_misses = 0 if pass_through else scan_count
            expected_pt_reads = scan_count if pass_through else 0
            expected_serviced = 0 if pass_through else scan_count

            req_checks = [
                ("read hits", stats.request_stats.read.hits,
                 stats_perc.request_stats.read.hits, 0, 0),
                ("read deferred", stats.request_stats.read.deferred,
                 stats_perc.request_stats.read.deferred, 0, 0),
                ("read part_misses", stats.request_stats.read.part_misses,
                 stats_perc.request_stats.read.part_misses, 0, 0),
                ("read full_misses", stats.request_stats.read.full_misses,
                 stats_perc.request_stats.read.full_misses,
                 expected_read_misses, 100 if not pass_through else 0),
                ("read total", stats.request_stats.read.total,
                 stats_perc.request_stats.read.total,
                 expected_read_misses, 100 if not pass_through else 0),
                ("write hits", stats.request_stats.write.hits,
                 stats_perc.request_stats.write.hits, 0, 0),
                ("write deferred", stats.request_stats.write.deferred,
                 stats_perc.request_stats.write.deferred, 0, 0),
                ("write part_misses", stats.request_stats.write.part_misses,
                 stats_perc.request_stats.write.part_misses, 0, 0),
                ("write full_misses", stats.request_stats.write.full_misses,
                 stats_perc.request_stats.write.full_misses, 0, 0),
                ("write total", stats.request_stats.write.total,
                 stats_perc.request_stats.write.total, 0, 0),
                ("pass-through reads", stats.request_stats.pass_through_reads,
                 stats_perc.request_stats.pass_through_reads,
                 expected_pt_reads, 100 if pass_through else 0),
                ("pass-through writes", stats.request_stats.pass_through_writes,
                 stats_perc.request_stats.pass_through_writes, 0, 0),
                ("serviced", stats.request_stats.requests_serviced,
                 stats_perc.request_stats.requests_serviced,
                 expected_serviced, 100 if not pass_through else 0),
                ("total", stats.request_stats.requests_total,
                 stats_perc.request_stats.requests_total, scan_count, 100),
            ]
            for name, val, val_perc, exp, exp_perc in req_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}request {name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(
                        f"{msg}request {name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check initial block statistics (partition scan effects)"):
        expected_cache_writes = scan_size.value if inserts_reads else 0

        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}) initial: "

            blk_checks = [
                ("exp_obj reads", stats.block_stats.exp_obj.reads.value,
                 stats_perc.block_stats.exp_obj.reads,
                 scan_size.value, 100),
                ("exp_obj writes", stats.block_stats.exp_obj.writes.value,
                 stats_perc.block_stats.exp_obj.writes, 0, 0),
                ("exp_obj total", stats.block_stats.exp_obj.total.value,
                 stats_perc.block_stats.exp_obj.total,
                 scan_size.value, 100),
                ("core reads", stats.block_stats.core.reads.value,
                 stats_perc.block_stats.core.reads,
                 scan_size.value, 100),
                ("core writes", stats.block_stats.core.writes.value,
                 stats_perc.block_stats.core.writes, 0, 0),
                ("core total", stats.block_stats.core.total.value,
                 stats_perc.block_stats.core.total,
                 scan_size.value, 100),
                ("cache reads", stats.block_stats.cache.reads.value,
                 stats_perc.block_stats.cache.reads, 0, 0),
                ("cache writes", stats.block_stats.cache.writes.value,
                 stats_perc.block_stats.cache.writes,
                 expected_cache_writes, 100 if inserts_reads else 0),
                ("cache total", stats.block_stats.cache.total.value,
                 stats_perc.block_stats.cache.total,
                 expected_cache_writes, 100 if inserts_reads else 0),
            ]
            for name, val, val_perc, exp, exp_perc in blk_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}block {name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(
                        f"{msg}block {name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check initial error statistics"):
        for core in cores:
            error_stats = get_stats_dict(
                filter=[StatsFilter.err], cache_id=core.cache_id, core_id=core.core_id
            )
            msg = f"Core {core.path} ({cache_mode}) initial: "
            for stat_name in error_stats:
                value = get_stat_value(error_stats, stat_name)
                if value != 0:
                    TestRun.LOGGER.error(
                        f"{msg}error stat '{stat_name}' is {value}, expected 0\n")

    # -- IO ---------------------------------------------------------------

    with TestRun.step("Run fio"):
        fio = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.randwrite)
            .size(io_size)
            .offset(fio_offset)
            .direct()
        )
        for core in cores:
            fio.add_job().target(core.path)
        fio.run()
        sleep(3)

    # -- Post-IO statistics -----------------------------------------------
    #
    # Expected values combine partition scan effects with fio results.
    # Scan contributed reads (cached for InsertRead modes, pass-through
    # otherwise).  Fio contributed writes (cached for InsertWrite modes,
    # pass-through otherwise).  The 1 MiB fio offset keeps the two sets
    # of blocks apart so both effects are independently visible.

    with TestRun.step("Check usage statistics after IO"):
        expected_occupancy = (
            (scan_size.value if inserts_reads else 0)
            + (io_size.value if inserts_writes else 0)
        )
        expected_free = cache.size.value - expected_occupancy * cores_per_cache
        expected_clean = (
            (scan_size.value if inserts_reads else 0)
            + (io_size.value if (inserts_writes and not lazy_writes) else 0)
        )
        expected_dirty = io_size.value if (inserts_writes and lazy_writes) else 0
        expected_occupancy_perc = round(100 * expected_occupancy / cache.size.value, 1)
        expected_free_perc = round(100 * expected_free / cache.size.value, 1)
        if expected_occupancy > 0:
            expected_clean_perc = round(100 * expected_clean / expected_occupancy, 1)
            expected_dirty_perc = round(100 * expected_dirty / expected_occupancy, 1)
        else:
            expected_clean_perc = 0
            expected_dirty_perc = 0

        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}): "

            usage_checks = [
                ("occupancy", stats.usage_stats.occupancy.value,
                 stats_perc.usage_stats.occupancy,
                 expected_occupancy, expected_occupancy_perc),
                ("free", stats.usage_stats.free.value,
                 stats_perc.usage_stats.free,
                 expected_free, expected_free_perc),
                ("clean", stats.usage_stats.clean.value,
                 stats_perc.usage_stats.clean,
                 expected_clean, expected_clean_perc),
                ("dirty", stats.usage_stats.dirty.value,
                 stats_perc.usage_stats.dirty,
                 expected_dirty, expected_dirty_perc),
            ]
            for name, val, val_perc, exp, exp_perc in usage_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}{name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(f"{msg}{name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check request statistics after IO"):
        total_reqs = scan_count + io_value
        expected_read_misses = 0 if pass_through else scan_count
        expected_pt_reads = scan_count if pass_through else 0
        expected_write_misses = io_value if inserts_writes else 0
        expected_pt_writes = io_value if not inserts_writes else 0
        expected_serviced = (
            (0 if pass_through else scan_count)
            + (io_value if inserts_writes else 0)
        )

        def req_perc(n):
            return round(100 * n / total_reqs, 1)

        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}): "

            req_checks = [
                ("read hits", stats.request_stats.read.hits,
                 stats_perc.request_stats.read.hits, 0, 0),
                ("read deferred", stats.request_stats.read.deferred,
                 stats_perc.request_stats.read.deferred, 0, 0),
                ("read part_misses", stats.request_stats.read.part_misses,
                 stats_perc.request_stats.read.part_misses, 0, 0),
                ("read full_misses", stats.request_stats.read.full_misses,
                 stats_perc.request_stats.read.full_misses,
                 expected_read_misses, req_perc(expected_read_misses)),
                ("read total", stats.request_stats.read.total,
                 stats_perc.request_stats.read.total,
                 expected_read_misses, req_perc(expected_read_misses)),
                ("write hits", stats.request_stats.write.hits,
                 stats_perc.request_stats.write.hits, 0, 0),
                ("write deferred", stats.request_stats.write.deferred,
                 stats_perc.request_stats.write.deferred, 0, 0),
                ("write part_misses", stats.request_stats.write.part_misses,
                 stats_perc.request_stats.write.part_misses, 0, 0),
                ("write full_misses", stats.request_stats.write.full_misses,
                 stats_perc.request_stats.write.full_misses,
                 expected_write_misses, req_perc(expected_write_misses)),
                ("write total", stats.request_stats.write.total,
                 stats_perc.request_stats.write.total,
                 expected_write_misses, req_perc(expected_write_misses)),
                ("pass-through reads", stats.request_stats.pass_through_reads,
                 stats_perc.request_stats.pass_through_reads,
                 expected_pt_reads, req_perc(expected_pt_reads)),
                ("pass-through writes", stats.request_stats.pass_through_writes,
                 stats_perc.request_stats.pass_through_writes,
                 expected_pt_writes, req_perc(expected_pt_writes)),
                ("serviced", stats.request_stats.requests_serviced,
                 stats_perc.request_stats.requests_serviced,
                 expected_serviced, req_perc(expected_serviced)),
                ("total", stats.request_stats.requests_total,
                 stats_perc.request_stats.requests_total, total_reqs, 100),
            ]
            for name, val, val_perc, exp, exp_perc in req_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}request {name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(
                        f"{msg}request {name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check block statistics after IO"):
        expected_exp_obj_total = scan_size.value + io_size.value
        expected_core_writes = (
            0 if (inserts_writes and lazy_writes) else io_size.value
        )
        expected_cache_writes = (
            (scan_size.value if inserts_reads else 0)
            + (io_size.value if inserts_writes else 0)
        )
        expected_core_total = scan_size.value + expected_core_writes
        expected_cache_total = expected_cache_writes

        def perc_of(n, total):
            return round(100 * n / total, 1) if total else 0

        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}): "

            blk_checks = [
                ("exp_obj reads", stats.block_stats.exp_obj.reads.value,
                 stats_perc.block_stats.exp_obj.reads,
                 scan_size.value, perc_of(scan_size.value, expected_exp_obj_total)),
                ("exp_obj writes", stats.block_stats.exp_obj.writes.value,
                 stats_perc.block_stats.exp_obj.writes,
                 io_size.value, perc_of(io_size.value, expected_exp_obj_total)),
                ("exp_obj total", stats.block_stats.exp_obj.total.value,
                 stats_perc.block_stats.exp_obj.total,
                 expected_exp_obj_total, 100),
                ("core reads", stats.block_stats.core.reads.value,
                 stats_perc.block_stats.core.reads,
                 scan_size.value, perc_of(scan_size.value, expected_core_total)),
                ("core writes", stats.block_stats.core.writes.value,
                 stats_perc.block_stats.core.writes,
                 expected_core_writes, perc_of(expected_core_writes, expected_core_total)),
                ("core total", stats.block_stats.core.total.value,
                 stats_perc.block_stats.core.total,
                 expected_core_total, 100),
                ("cache reads", stats.block_stats.cache.reads.value,
                 stats_perc.block_stats.cache.reads, 0, 0),
                ("cache writes", stats.block_stats.cache.writes.value,
                 stats_perc.block_stats.cache.writes,
                 expected_cache_writes, perc_of(expected_cache_writes, expected_cache_total)),
                ("cache total", stats.block_stats.cache.total.value,
                 stats_perc.block_stats.cache.total,
                 expected_cache_total, perc_of(expected_cache_total, expected_cache_total)),
            ]
            for name, val, val_perc, exp, exp_perc in blk_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}block {name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(
                        f"{msg}block {name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check error statistics after IO"):
        for core in cores:
            error_stats = get_stats_dict(
                filter=[StatsFilter.err], cache_id=core.cache_id, core_id=core.core_id
            )
            msg = f"Core {core.path} ({cache_mode}): "
            for stat_name in error_stats:
                value = get_stat_value(error_stats, stat_name)
                if value != 0:
                    TestRun.LOGGER.error(
                        f"{msg}error stat '{stat_name}' is {value}, expected 0\n")

    # -- Cache-vs-cores sum check -----------------------------------------

    with TestRun.step("Check if cache statistics match sum of cores' statistics"):
        cache_stats_dict = get_stats_dict(filter=stat_filter, cache_id=cache.cache_id)
        cache_stats_values = {
            k: get_stat_value(cache_stats_dict, k)
            for k in cache_stats_dict if not k.endswith("[%]")
        }
        cores_stats_dicts = [
            get_stats_dict(filter=stat_filter, cache_id=core.cache_id, core_id=core.core_id)
            for core in cores
        ]
        cores_stats_values = [
            {k: get_stat_value(d, k) for k in d if not k.endswith("[%]")}
            for d in cores_stats_dicts
        ]

        for stat_name in cache_stats_values:
            if stat_name.startswith("Free"):
                continue
            cache_val = cache_stats_values[stat_name]
            try:
                cache_val = cache_val.value
            except AttributeError:
                pass
            core_sum = 0
            for j in range(cores_per_cache):
                val = cores_stats_values[j][stat_name]
                try:
                    val = val.value
                except AttributeError:
                    pass
                core_sum += val
            if core_sum != cache_val:
                TestRun.LOGGER.error(
                    f"Cache {cache.cache_id}: sum of cores' '{stat_name}' "
                    f"is {core_sum}, expected {cache_val}\n")

    # -- Reload -----------------------------------------------------------
    #
    # After reload, cached data persists but counters are reset.  The
    # kernel partition scan runs again on each exported object.  For
    # InsertRead modes the scan blocks are already cached → read hits,
    # no usage change.  For other modes the scan passes through, also
    # no usage change.

    with TestRun.step("Stop and load cache back"):
        casadm.stop_all_caches()
        cache = casadm.load_cache(cache_dev.partitions[0])

    with TestRun.step("Check usage statistics after reload"):
        # Usage expectations are unchanged — cached data persists and the
        # reload scan does not alter occupancy (hits for InsertRead modes,
        # pass-through for others).
        for core in cores:
            stats = core.get_statistics(stat_filter=stat_filter)
            stats_perc = core.get_statistics(stat_filter=stat_filter, percentage_val=True)
            msg = f"Core {core.path} ({cache_mode}) after reload: "

            usage_checks = [
                ("occupancy", stats.usage_stats.occupancy.value,
                 stats_perc.usage_stats.occupancy,
                 expected_occupancy, expected_occupancy_perc),
                ("free", stats.usage_stats.free.value,
                 stats_perc.usage_stats.free,
                 expected_free, expected_free_perc),
                ("clean", stats.usage_stats.clean.value,
                 stats_perc.usage_stats.clean,
                 expected_clean, expected_clean_perc),
                ("dirty", stats.usage_stats.dirty.value,
                 stats_perc.usage_stats.dirty,
                 expected_dirty, expected_dirty_perc),
            ]
            for name, val, val_perc, exp, exp_perc in usage_checks:
                if val != exp:
                    TestRun.LOGGER.error(f"{msg}{name} is {val}, expected {exp}\n")
                if val_perc != exp_perc:
                    TestRun.LOGGER.error(f"{msg}{name} % is {val_perc}, expected {exp_perc}\n")

    with TestRun.step("Check error statistics after reload"):
        for core in cores:
            error_stats = get_stats_dict(
                filter=[StatsFilter.err], cache_id=core.cache_id, core_id=core.core_id
            )
            msg = f"Core {core.path} ({cache_mode}) after reload: "
            for stat_name in error_stats:
                value = get_stat_value(error_stats, stat_name)
                if value != 0:
                    TestRun.LOGGER.error(
                        f"{msg}error stat '{stat_name}' is {value}, expected 0\n")
