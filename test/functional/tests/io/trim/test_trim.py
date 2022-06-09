#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import os
import re
import time

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheModeTrait, CleaningPolicy, SeqCutOffPolicy
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet
from test_tools import fs_utils
from test_tools.blktrace import BlkTrace, BlkTraceMask, RwbsKind
from test_tools.disk_utils import Filesystem, check_if_device_supports_trim
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from test_utils import os_utils
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand]))
def test_trim_start_discard():
    """
    title: Check discarding cache device at cache start
    description: |
       Create 2 partitions on trim-supporting device, write pattern to both partitions,
       start blktrace against first one, start cache on first partition and check if discard
       requests were sent at all and only to the first partition.
    pass_criteria:
      - Partition used for cache is discarded.
      - Second partition is untouched - written pattern is preserved.
    """
    with TestRun.step("Clearing dmesg"):
        TestRun.executor.run_expect_success("dmesg -C")

    with TestRun.step("Preparing cache device"):
        dev = TestRun.disks['cache']
        dev.create_partitions([Size(500, Unit.MebiByte), Size(500, Unit.MebiByte)])
        cas_part = dev.partitions[0]
        non_cas_part = dev.partitions[1]

    with TestRun.step("Writing different pattern on partitions"):
        cas_fio = write_pattern(cas_part.path)
        non_cas_fio = write_pattern(non_cas_part.path)
        non_cas_fio.verification_with_pattern("0xdeadbeef")
        cas_fio.run()
        non_cas_fio.run()

    # TODO add blktracing for non-cas part
    with TestRun.step("Starting blktrace against first (cache) partition"):
        blktrace = BlkTrace(cas_part, BlkTraceMask.discard)
        blktrace.start_monitoring()

    with TestRun.step("Starting cache"):
        cache = casadm.start_cache(cas_part, force=True)
        metadata_size = get_metadata_size_from_dmesg()

    with TestRun.step("Stop blktrace and check if discard requests were issued"):
        cache_reqs = blktrace.stop_monitoring()
        cache_part_start = cas_part.begin

        # CAS should discard cache device during cache start
        if len(cache_reqs) == 0:
            TestRun.fail("No discard requests issued to the cas partition!")

        non_meta_sector = (cache_part_start + metadata_size).get_value(Unit.Blocks512)
        non_meta_size = (cas_part.size - metadata_size).get_value(Unit.Byte)
        for req in cache_reqs:
            if req.sector_number != non_meta_sector:
                TestRun.fail(f"Discard request issued to wrong sector: {req.sector_number}, "
                             f"expected: {non_meta_sector}")
            if req.byte_count != non_meta_size:
                TestRun.fail(f"Discard request issued with wrong bytes count: {req.byte_count}, "
                             f"expected: {non_meta_size} bytes")

    with TestRun.step("Check if data on the second part hasn't changed"):
        non_cas_fio.read_write(ReadWrite.read)
        non_cas_fio.run()

    if int(dev.get_discard_zeroes_data()):
        with TestRun.step("Check if CAS zeroed data section on the cache device"):
            cas_fio.offset(metadata_size)
            cas_fio.verification_with_pattern("0x00")
            cas_fio.read_write(ReadWrite.read)
            cas_fio.run()

    with TestRun.step("Stopping cache"):
        cache.stop()


@pytest.mark.require_disk("ssd1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("ssd2", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_plugin("power_control")
def test_trim_propagation():
    """
    title: Trim request not propagated to cache device
    description: |
      Sending trim request to exported object discards only data. The data from cache
      is invalidated but the trim request is not propagated to cache device and metadata
      of other cache lines is not affected.
    pass_criteria:
      - No system crash.
      - No discards detected on caching device
      - No data corruption after power failure.
    """

    with TestRun.step(f"Create partitions"):
        TestRun.disks["ssd1"].create_partitions([Size(43, Unit.MegaByte)])
        TestRun.disks["ssd2"].create_partitions([Size(512, Unit.KiloByte)])

        cache_dev = TestRun.disks["ssd1"].partitions[0]
        core_dev = TestRun.disks["ssd2"].partitions[0]

        if not check_if_device_supports_trim(cache_dev):
            raise Exception("Cache device doesn't support discards")
        if not check_if_device_supports_trim(core_dev):
            raise Exception("Core device doesn't support discards")

    with TestRun.step(f"Disable udev"):
        os_utils.Udev.disable()

    with TestRun.step(f"Prepare cache instance in WB with one core"):
        cache = casadm.start_cache(cache_dev, CacheMode.WB, force=True)
        core = cache.add_core(core_dev)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.purge_cache()

    with TestRun.step(f"Fill exported object with dirty data"):
        core_size_4k = core.get_statistics().config_stats.core_size.get_value(Unit.Blocks4096)
        core_size_4k = int(core_size_4k)

        cas_fio = write_pattern(core.path)
        cas_fio.verification_with_pattern("0xdeadbeef")
        cas_fio.run()

        dirty_4k = cache.get_statistics().usage_stats.dirty.get_value(Unit.Blocks4096)

        if dirty_4k != core_size_4k:
            TestRun.fail(
                f"Failed to fill cache. Expected dirty blocks: {core_size_4k}, "
                f"actual value {dirty_4k}"
            )

    with TestRun.step(f"Discard 4k of data on exported object"):
        TestRun.executor.run_expect_success(f"blkdiscard {core.path} --length 4096 --offset 0")
        old_occupancy = cache.get_statistics().usage_stats.occupancy.get_value(Unit.Blocks4096)

    with TestRun.step("Power cycle"):
        power_control = TestRun.plugin_manager.get_plugin("power_control")
        power_control.power_cycle()
        os_utils.Udev.disable()

    with TestRun.step("Load cache"):
        cache = casadm.start_cache(cache_dev, load=True)

    with TestRun.step("Check if occupancy after dirty shutdown is correct"):
        new_occupancy = cache.get_statistics().usage_stats.occupancy.get_value(Unit.Blocks4096)
        if new_occupancy != old_occupancy:
            TestRun.LOGGER.error(
                f"Expected occupancy after dirty shutdown: {old_occupancy}. "
                f"Actuall: {new_occupancy})"
            )

    with TestRun.step("Verify data after dirty shutdown"):
        cas_fio.read_write(ReadWrite.read)
        cas_fio.offset(Unit.Blocks4096)
        cas_fio.run()


@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.InsertWrite))
@pytest.mark.parametrizex("filesystem", Filesystem)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("trim_support_cache_core", [(False, True), (True, False), (True, True)])
@pytest.mark.require_disk("ssd1", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("ssd2", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_trim_device_discard_support(
        trim_support_cache_core, cache_mode, filesystem, cleaning_policy):
    """
        title: Trim requests supported on various cache and core devices.
        description: |
          Handling trim requests support when various combination of SSD and HDD are used as
          cache and core.
        pass_criteria:
          - No system crash.
          - Discards detected on CAS.
          - Discards detected on SSD device when it is used as core.
          - Discards not detected on HDD device used as cache or core.
          - Discards not detected on cache device.
    """

    mount_point = "/mnt"

    with TestRun.step(f"Create partitions on SSD and HDD devices. Create filesystem."):
        TestRun.disks["ssd1"].create_partitions([Size(1, Unit.GibiByte)])
        TestRun.disks["ssd2"].create_partitions([Size(1, Unit.GibiByte)])
        disk_not_supporting_trim = None
        for disk in TestRun.dut.disks:
            if not check_if_device_supports_trim(disk):
                disk_not_supporting_trim = disk
                break
        if disk_not_supporting_trim is None:
            raise Exception("There is no device not supporting trim on given DUT.")

        disk_not_supporting_trim.create_partitions([Size(1, Unit.GibiByte)])
        ssd1_dev = TestRun.disks["ssd1"].partitions[0]
        ssd2_dev = TestRun.disks["ssd2"].partitions[0]
        dev_not_supporting_trim = disk_not_supporting_trim.partitions[0]

    with TestRun.step(f"Start cache and add core."):
        cache_dev = ssd1_dev if trim_support_cache_core[0] else dev_not_supporting_trim
        core_dev = ssd2_dev if trim_support_cache_core[1] else dev_not_supporting_trim

        cache = casadm.start_cache(cache_dev, cache_mode, force=True)
        cache.set_cleaning_policy(cleaning_policy)

        core_dev.create_filesystem(filesystem)
        core = cache.add_core(core_dev)

    with TestRun.step("Mount filesystem with discard option."):
        core.mount(mount_point, ["discard"])

    with TestRun.step("Create random file."):
        test_file = fs_utils.create_random_test_file(os.path.join(mount_point, "test_file"),
                                                     core_dev.size * 0.2)
        occupancy_before = core.get_occupancy()
        TestRun.LOGGER.info(str(core.get_statistics()))

    with TestRun.step("Start blktrace monitoring on all devices."):
        blktraces = start_monitoring(core_dev, cache_dev, core)

    with TestRun.step("Remove file."):
        os_utils.sync()
        os_utils.drop_caches()
        test_file.remove()

    if filesystem == Filesystem.xfs:
        with TestRun.step(
            "Since issuing discard reqs is a lazy operation on XFS "
            "write a small amount of data to the partition"
        ):
            test_file = fs_utils.create_random_test_file(
                os.path.join(mount_point, "test_file"), core_dev.size * 0.1
            )

    with TestRun.step(
            "Ensure that discards were detected by blktrace on proper devices."):
        discard_expected = {"core": trim_support_cache_core[1], "cache": False, "cas": True}
        TestRun.LOGGER.info(f"Discards expected: core - {trim_support_cache_core[1]}, "
                            f"cache - False, cas - True")
        stop_monitoring_and_check_discards(blktraces, discard_expected)

    with TestRun.step("Ensure occupancy reduced."):
        occupancy_after = core.get_occupancy()
        TestRun.LOGGER.info(str(core.get_statistics()))

        if occupancy_after >= occupancy_before:
            TestRun.LOGGER.error("Occupancy on core after removing test file greater than before.")
        else:
            TestRun.LOGGER.info("Occupancy on core after removing test file smaller than before.")

    with TestRun.step("Check CAS sysfs properties values."):
        check_sysfs_properties(cache, cache_dev, core, core_dev.parent_device,
                               core_supporting_discards=trim_support_cache_core[1])


def check_sysfs_properties(cache, cache_dev, core, core_disk, core_supporting_discards):
    expected_discard_max_bytes = int(core_disk.get_discard_max_bytes()) \
        if core_supporting_discards else int(cache_dev.size.get_value())
    cas_discard_max_bytes = int(core.get_discard_max_bytes())
    compare_properties(cas_discard_max_bytes, expected_discard_max_bytes, "discard_max_bytes")

    expected_discard_granularity = int(core_disk.get_discard_granularity()) \
        if core_supporting_discards else int(cache.get_cache_line_size())
    cas_discard_granularity = int(core.get_discard_granularity())
    compare_properties(
        cas_discard_granularity, expected_discard_granularity, "discard_granularity")

    cas_discard_zeroes_data = int(core.get_discard_zeroes_data())
    if cas_discard_zeroes_data == 0:
        TestRun.LOGGER.info("CAS discard_zeroes_data value equals 0 as expected.")
    else:
        TestRun.LOGGER.error(f"CAS discard_zeroes_data value equals {cas_discard_zeroes_data}. "
                             "Expected value for this property is 0.")


def compare_properties(value, expected_value, property_name):
    if expected_value == value:
        TestRun.LOGGER.info(f"CAS {property_name} value is correct.")
        return
    TestRun.LOGGER.error(f"CAS property {property_name} value equals {value} and differs "
                         f"from expected value: {expected_value}.")


def stop_monitoring_and_check_discards(blktraces, discard_support):
    time.sleep(60)
    os_utils.sync()
    os_utils.drop_caches()
    time.sleep(5)

    discard_flag = RwbsKind.D  # Discard
    for key in blktraces.keys():
        output = blktraces[key].stop_monitoring()
        discard_messages = [h for h in output if discard_flag in h.rwbs]
        check_discards(len(discard_messages), blktraces[key].device, discard_support[key])


def check_discards(discards_count, device, discards_expected):
    if discards_expected:
        if discards_count > 0:
            TestRun.LOGGER.info(
                f"{discards_count} TRIM instructions generated for {device.path}")
        else:
            TestRun.LOGGER.error(f"No TRIM instructions found in requests to {device.path}")
    else:
        if discards_count > 0:
            TestRun.LOGGER.error(
                f"{discards_count} TRIM instructions generated for {device.path}")
        else:
            TestRun.LOGGER.info(f"No TRIM instructions found in requests to {device.path}")


def start_monitoring(core_dev, cache_dev, cas_dev):
    blktrace_core_dev = BlkTrace(core_dev, BlkTraceMask.discard)
    blktrace_cache_dev = BlkTrace(cache_dev, BlkTraceMask.discard)
    blktrace_cas = BlkTrace(cas_dev, BlkTraceMask.discard)

    blktrace_core_dev.start_monitoring()
    blktrace_cache_dev.start_monitoring()
    blktrace_cas.start_monitoring()

    return {"core": blktrace_core_dev, "cache": blktrace_cache_dev, "cas": blktrace_cas}


def write_pattern(device):
    return (Fio().create_command()
            .io_engine(IoEngine.libaio)
            .read_write(ReadWrite.write)
            .target(device)
            .direct()
            .verification_with_pattern()
            )


def get_metadata_size_from_dmesg():
    dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout
    for s in dmesg_out.split("\n"):
        if "Hash offset" in s:
            offset = re.search("[0-9]* kiB", s).group()
            offset = Size(int(re.search("[0-9]*", offset).group()), Unit.KibiByte)
        if "Hash size" in s:
            size = re.search("[0-9]* kiB", s).group()
            size = Size(int(re.search("[0-9]*", size).group()), Unit.KibiByte)

    # Metadata is 128KiB aligned
    return (offset + size).align_up(128 * Unit.KibiByte.value)
