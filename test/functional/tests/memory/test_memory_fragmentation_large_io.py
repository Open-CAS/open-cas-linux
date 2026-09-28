#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import re
import time

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.dmesg import clear_dmesg, get_dmesg
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite, VerifyMethod
from test_tools.fs_tools import create_directory, is_mounted, read_file, remove
from test_tools.memory import get_mem_free, mount_ramfs, unmount_ramfs
from test_tools.os_tools import drop_caches, MEMORY_MOUNT_POINT
from type_def.size import Size, Unit

contiguous_block_size = Size(256, Unit.KibiByte)
contiguous_block_order = int(contiguous_block_size.get_value(Unit.Blocks4096)).bit_length() - 1
fragment_files = [posixpath.join(MEMORY_MOUNT_POINT, f"fragment_{i}") for i in range(2)]
soak_mount_point = "/mnt/soak"
thp_defrag_path = "/sys/kernel/mm/transparent_hugepage/defrag"


@pytest.fixture
def restore_memory_state():
    """Releases the memory allocated by the test and restores the kernel memory settings"""
    nr_hugepages = get_nr_hugepages()
    proactiveness = read_setting("/proc/sys/vm/compaction_proactiveness")
    extfrag_threshold = read_setting("/proc/sys/vm/extfrag_threshold")
    thp_defrag = read_setting(thp_defrag_path)
    swaps = TestRun.executor.run_expect_success("swapon --show=NAME --noheadings").stdout.split()

    yield

    if is_mounted(soak_mount_point):
        TestRun.executor.run_expect_success(f"umount {soak_mount_point}")
    if is_mounted(MEMORY_MOUNT_POINT):
        unmount_ramfs()
    set_nr_hugepages(nr_hugepages)
    write_setting("/proc/sys/vm/compaction_proactiveness", proactiveness)
    write_setting("/proc/sys/vm/extfrag_threshold", extfrag_threshold)
    write_setting(thp_defrag_path, thp_defrag)
    for swap in swaps:
        TestRun.executor.run(f"swapon {swap}")


@pytest.mark.parametrize(
    "io_size, io_depth",
    [
        (Size(4, Unit.MiB), 16),
        (Size(32, Unit.MiB), 16),
        (Size(48, Unit.MiB), 8),
        (Size(128, Unit.MiB), 4),
        (Size(512, Unit.MiB), 1),
        (Size(1, Unit.GiB), 1),
    ],
    ids=lambda value: (
        f"{value.get_value(value.unit):g}{value.unit.get_short_name()}"
        if isinstance(value, Size)
        else None
    ),
)
@pytest.mark.parametrizex("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.usefixtures("restore_memory_state")
def test_memory_fragmentation_large_io(io_size, io_depth, cls):
    """
    title: Large I/O with fragmented memory
    description: |
        Verify that large I/O requests are handled correctly when system memory is so
        fragmented that no large physically contiguous block is available.
    pass_criteria:
      - No I/O errors.
      - No data corruption.
      - No page allocation failures reported by CAS.
    """

    with TestRun.step("Prepare devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(10, Unit.GiB)])
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(10, Unit.GiB)])

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(
            cache_dev.partitions[0], CacheMode.WT, cls, force=True
        )
        core = cache.add_core(core_dev.partitions[0])

    hugepage_size = get_hugepage_size()

    with TestRun.step("Prevent the kernel from undoing the fragmentation"):
        # Stop kcompactd from migrating movable pages into the holes, both
        # proactively and on high order allocation failures
        write_setting("/proc/sys/vm/compaction_proactiveness", 0)
        write_setting("/proc/sys/vm/extfrag_threshold", 1000)
        # Swapping out tmpfs pages would free the blocks consumed by them
        TestRun.executor.run_expect_success("swapoff --all")

    with TestRun.step("Reserve huge pages for fio buffers"):
        # Physically contiguous huge page buffers let direct I/O be submitted in bios
        # as big as possible even when the rest of the memory is fragmented
        drop_caches()
        write_setting("/proc/sys/vm/compact_memory", 1)
        fio_hugepages = io_size * io_depth // hugepage_size + 16
        if set_nr_hugepages(fio_hugepages) < fio_hugepages:
            TestRun.fail(f"Failed to reserve {fio_hugepages} huge pages for fio")

    with TestRun.step("Fill memory with interleaved pages of two ramfs files"):
        mount_ramfs()
        mem_free = get_mem_free()
        # Free blocks are taken smallest first, so the fill has to go down close to
        # the watermarks to leave as few high order blocks behind as possible
        fill_size = mem_free - get_unusable_mem() - Size(64, Unit.MebiByte)
        fill_size = fill_size.align_down(Unit.Blocks4096.value * len(fragment_files))
        TestRun.LOGGER.info(
            f"Free memory: {mem_free.get_value(Unit.MebiByte):.2f} MiB, "
            f"filling: {fill_size.get_value(Unit.MebiByte):.2f} MiB"
        )
        # Round-robin 4 KiB writes make consecutive physical pages belong to
        # alternating files. Pages of ramfs can be neither reclaimed nor migrated,
        # so memory compaction cannot defragment them.
        (
            Fio()
            .create_command()
            .file_name(":".join(fragment_files))
            .io_engine(IoEngine.psync)
            .read_write(ReadWrite.write)
            .block_size(Size(1, Unit.Blocks4096))
            .size(fill_size)
            .set_param("file_service_type", "roundrobin")
            .set_param("fallocate", "none")
            .run()
        )

    with TestRun.step("Free every other page"):
        remove(fragment_files[1], force=True)
        drop_caches()

    with TestRun.step("Allocate remaining high order blocks with tmpfs large folios"):
        # What is left of the free memory outside of the single page holes, mostly
        # below the watermarks during the fill, is now allocatable again. tmpfs backs
        # large writes with large folios, which consume exactly these blocks.
        # Direct reclaim on these allocations also evicts large page cache folios
        # that reclaim would otherwise turn into high order blocks during the I/O.
        thp_defrag = read_setting(thp_defrag_path)
        write_setting(thp_defrag_path, "always")
        create_directory(soak_mount_point, parents=True)
        TestRun.executor.run_expect_success(
            f"mount -t tmpfs -o huge=always,size={int(mem_free)} tmpfs {soak_mount_point}"
        )
        for i in range(10):
            # Let reclaim and compaction triggered by the fill settle down first
            time.sleep(5)
            capacity = get_free_contiguous_blocks()
            if capacity == 0 and i > 1:
                break
            soak_size = get_free_blocks_size(1) + Size(16, Unit.MebiByte)
            bs = Size(1, Unit.MebiByte)
            (
                Dd()
                .input("/dev/zero")
                .output(posixpath.join(soak_mount_point, f"soak_{i}"))
                .block_size(bs)
                .count(soak_size // bs + 1)
                .run()
            )
        write_setting(thp_defrag_path, thp_defrag)

    with TestRun.step("Check that memory is fragmented"):
        TestRun.LOGGER.info(
            f"Free memory: {get_mem_free().get_value(Unit.MebiByte):.2f} MiB"
        )
        capacity = get_free_contiguous_blocks()
        if capacity:
            TestRun.fail(
                f"Memory is not fragmented enough: {capacity} free contiguous blocks of "
                f"{contiguous_block_size.get_value(Unit.KibiByte):.0f} KiB still available"
            )

    with TestRun.step("Run large direct I/O with data verification"):
        clear_dmesg()
        fio = (
            Fio()
            .create_command()
            .target(core)
            .direct()
            .io_engine(IoEngine.libaio)
            .io_depth(io_depth)
            .read_write(ReadWrite.write)
            .block_size(io_size)
            .size(max(Size(4, Unit.GibiByte), io_size * 4))
            .verify(VerifyMethod.md5)
            .do_verify()
            .set_param("iomem", "shmhuge")
            .set_param("hugepage-size", int(hugepage_size))
        )
        try:
            result = fio.run()
        except Exception as e:
            TestRun.fail(f"fio failed:\n{e}")
        errors = sum(job.total_errors() for job in result)
        if errors:
            TestRun.fail(f"fio reported {errors} errors")

    with TestRun.step("Check for page allocation failures in CAS"):
        dmesg = get_dmesg()
        if "page allocation failure" in dmesg and "[cas_cache]" in dmesg:
            TestRun.fail(f"CAS hit a page allocation failure:\n{dmesg}")


def read_setting(path):
    output = read_file(path)
    # Selected option of sysfs multiple choice setting is put in brackets
    selected = re.search(r"\[(\S+)\]", output)
    return selected.group(1) if selected else output.strip()


def write_setting(path, value):
    TestRun.executor.run_expect_success(f"echo {value} > {path}")


def get_hugepage_size():
    hugepage_size = re.search(r"^Hugepagesize:\s+(\d+) kB", read_file("/proc/meminfo"), re.M)
    return Size(int(hugepage_size.group(1)), Unit.KibiByte)


def get_nr_hugepages():
    return int(read_file("/proc/sys/vm/nr_hugepages"))


def set_nr_hugepages(count: int):
    """Requests the huge page pool size, returns the number of huge pages actually allocated"""
    write_setting("/proc/sys/vm/nr_hugepages", count)
    nr_hugepages = get_nr_hugepages()
    TestRun.LOGGER.info(f"Huge pages allocated: {nr_hugepages}/{count}")
    return nr_hugepages


def get_unusable_mem():
    """
    Returns amount of free memory that regular kernel and user allocations cannot use:
    pages below the high watermark and pages protected by lowmem_reserve of each zone
    """
    output = read_file("/proc/zoneinfo")
    zones = []
    for line in output.splitlines():
        if match := re.match(r"Node\s+\d+,\s+zone\s+(\S+)", line):
            zones.append({"name": match.group(1)})
        elif match := re.match(r"\s+pages free\s+(\d+)", line):
            zones[-1]["free"] = int(match.group(1))
        elif match := re.match(r"\s+high\s+(\d+)", line):
            zones[-1]["high"] = int(match.group(1))
        elif match := re.match(r"\s+protection:\s+\((.*)\)", line):
            zones[-1]["protection"] = [int(p) for p in match.group(1).split(",")]
    normal_idx = [zone["name"] for zone in zones].index("Normal")
    unusable_pages = sum(
        min(zone["free"], zone["high"] + zone["protection"][normal_idx])
        for zone in zones
        if "free" in zone
    )
    return Size(unusable_pages, Unit.Blocks4096)


def get_free_blocks(min_order: int):
    """
    Yields (order, count) of free blocks of at least given order. Only zones and migrate
    types from which a regular kernel allocation may be served are taken into account.
    """
    output = read_file("/proc/pagetypeinfo")
    for line in output.splitlines():
        match = re.match(r"Node\s+\d+,\s+zone\s+(\S+),\s+type\s+(\S+)\s+(.*)", line)
        if not match:
            continue
        zone, migrate_type, counts = match.groups()
        if zone == "DMA" or migrate_type not in ["Unmovable", "Movable", "Reclaimable"]:
            continue
        counts = [int(count.lstrip(">")) for count in counts.split()]
        for order, count in enumerate(counts):
            if order >= min_order:
                yield order, count


def get_free_contiguous_blocks():
    """Returns how many blocks of contiguous_block_size the free memory can provide"""
    capacity = sum(
        count << (order - contiguous_block_order)
        for order, count in get_free_blocks(contiguous_block_order)
    )
    TestRun.LOGGER.info(
        f"Free contiguous blocks of {contiguous_block_size.get_value(Unit.KibiByte):.0f} KiB: "
        f"{capacity}"
    )
    return capacity


def get_free_blocks_size(min_order: int):
    """Returns total size of free blocks of at least given order"""
    pages = sum(count << block_order for block_order, count in get_free_blocks(min_order))
    return Size(pages, Unit.Blocks4096)
