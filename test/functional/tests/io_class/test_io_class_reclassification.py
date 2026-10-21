#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from type_def.size import Size, Unit
from tests.io_class.io_class_common import (
    prepare,
    ioclass_config_path,
    get_io_class_occupancy,
    get_io_class_dirty,
)

region_size = Size(16, Unit.MebiByte)
region_sectors = int(region_size.get_value(Unit.Blocks512))


def lba_rule(region):
    first = region * region_sectors
    last = first + region_sectors - 1
    return f"lba:ge:{first}&lba:le:{last}&done"


def add_lba_ioclass(ioclass_id, region):
    ioclass_config.add_ioclass(
        ioclass_id=ioclass_id,
        eviction_priority=1,
        allocation="1.00",
        rule=lba_rule(region),
        ioclass_config_path=ioclass_config_path,
    )


def run_region_io(core, region, write):
    dd = Dd().block_size(Size(1, Unit.MebiByte)).count(int(region_size.get_value(Unit.MebiByte)))
    if write:
        dd.input("/dev/urandom").output(core.path).seek(
            region * int(region_size.get_value(Unit.MebiByte))
        ).oflag("direct")
    else:
        dd.input(core.path).output("/dev/null").skip(
            region * int(region_size.get_value(Unit.MebiByte))
        ).iflag("direct")
    dd.run()


def regions_md5(core, regions):
    output = TestRun.executor.run_expect_success(
        f"dd if={core.path} bs=1M count={regions * int(region_size.get_value(Unit.MebiByte))} "
        f"iflag=direct | md5sum"
    )
    return output.stdout.split()[0]


def check_usage(cache, ioclass_id, expected, check_dirty=True):
    occupancy = get_io_class_occupancy(cache, ioclass_id)
    if occupancy != expected:
        TestRun.LOGGER.error(
            f"Wrong occupancy of IO class {ioclass_id}. Expected {expected}, got {occupancy}"
        )
    if check_dirty:
        dirty = get_io_class_dirty(cache, ioclass_id)
        if dirty != expected:
            TestRun.LOGGER.error(
                f"Wrong dirty data of IO class {ioclass_id}. Expected {expected}, got {dirty}"
            )


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("keep_classification", [False, True])
def test_io_class_reclassify_on_remove(keep_classification):
    """
    title: Test reclassification of data after removing IO class.
    description: |
      Fill two IO classes with dirty data, remove one of them from the configuration
      and load it. Check that data of all the IO classes is moved to the unclassified
      IO class, unless the classification is kept, in which case only data of the
      removed IO class is moved. Then check that accessed data is classified again.
    pass_criteria:
      - Data of all the IO classes is reclassified by default.
      - With --keep-classification only data of the removed IO class is reclassified.
      - Accessed data is classified according to the new configuration.
      - Cache occupancy and data stay unchanged.
    """
    default_id = ioclass_config.DEFAULT_IO_CLASS_ID
    kept_id, removed_id = 1, 2
    zero = Size.zero()

    with TestRun.step("Prepare cache and core"):
        cache, core = prepare(default_allocation="1.00")

    with TestRun.step("Load configuration with IO classes for two LBA regions"):
        add_lba_ioclass(kept_id, region=0)
        add_lba_ioclass(removed_id, region=1)
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Write data to both regions"):
        run_region_io(core, region=0, write=True)
        run_region_io(core, region=1, write=True)
        md5_before = regions_md5(core, 2)
        check_usage(cache, kept_id, region_size)
        check_usage(cache, removed_id, region_size)
        check_usage(cache, default_id, zero)

    with TestRun.step("Remove one IO class and load the configuration"):
        ioclass_config.remove_ioclass(removed_id, ioclass_config_path)
        casadm.load_io_classes(
            cache_id=cache.cache_id,
            file=ioclass_config_path,
            keep_classification=keep_classification,
        )

    with TestRun.step("Check that data was reclassified"):
        if keep_classification:
            check_usage(cache, kept_id, region_size)
            check_usage(cache, default_id, region_size)
        else:
            check_usage(cache, kept_id, zero)
            check_usage(cache, default_id, region_size * 2)

        if cache.get_occupancy() != region_size * 2:
            TestRun.LOGGER.error(f"Wrong cache occupancy: {cache.get_occupancy()}")
        if cache.get_dirty_blocks() != region_size * 2:
            TestRun.LOGGER.error(f"Wrong amount of dirty data: {cache.get_dirty_blocks()}")

    with TestRun.step("Read data of the remaining IO class"):
        run_region_io(core, region=0, write=False)

    with TestRun.step("Check that read data was classified again"):
        check_usage(cache, kept_id, region_size)
        check_usage(cache, default_id, region_size)

    with TestRun.step("Flush cache and check data consistency"):
        cache.flush_cache()
        if cache.get_dirty_blocks() != zero:
            TestRun.LOGGER.error(f"Dirty data left after flush: {cache.get_dirty_blocks()}")
        if regions_md5(core, 2) != md5_before:
            TestRun.LOGGER.error("Data changed after reclassification")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("keep_classification", [False, True])
def test_io_class_reclassify_on_rule_change(keep_classification):
    """
    title: Test reclassification of data after changing IO class rule.
    description: |
      Fill an IO class with data, change its classification rule and load the
      configuration. Check that by default its data is moved to the unclassified
      IO class immediately, and with the classification kept it stays in the IO
      class until accessed.
    pass_criteria:
      - Data of the IO class with modified rule is reclassified by default.
      - With --keep-classification data stays in the IO class until accessed.
      - Accessed data is classified according to the new rule.
    """
    default_id = ioclass_config.DEFAULT_IO_CLASS_ID
    ioclass_id = 1
    zero = Size.zero()

    with TestRun.step("Prepare cache and core"):
        cache, core = prepare(default_allocation="1.00")

    with TestRun.step("Load configuration with IO class for the first LBA region"):
        add_lba_ioclass(ioclass_id, region=0)
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Write data to the first region"):
        run_region_io(core, region=0, write=True)
        check_usage(cache, ioclass_id, region_size)
        check_usage(cache, default_id, zero)

    with TestRun.step("Change the IO class rule to the second LBA region"):
        ioclass_config.remove_ioclass(ioclass_id, ioclass_config_path)
        add_lba_ioclass(ioclass_id, region=1)
        casadm.load_io_classes(
            cache_id=cache.cache_id,
            file=ioclass_config_path,
            keep_classification=keep_classification,
        )

    with TestRun.step("Check that data was reclassified only if requested"):
        if keep_classification:
            check_usage(cache, ioclass_id, region_size)
            check_usage(cache, default_id, zero)
        else:
            check_usage(cache, ioclass_id, zero)
            check_usage(cache, default_id, region_size)

    with TestRun.step("Read data of the first region"):
        run_region_io(core, region=0, write=False)

    with TestRun.step("Check that read data was classified according to the new rule"):
        check_usage(cache, ioclass_id, zero)
        check_usage(cache, default_id, region_size)
