#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import time
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode
from api.cas.cli import script_connect_cache_cmd, script_disconnect_cache_cmd
from connection.utils.asynchronous import start_async_func
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import IoEngine, ReadWrite
from test_tools.fs_tools import crc32sum
from test_tools.os_tools import sync
from type_def.size import Size, Unit


CACHE_SIZE = Size(2, Unit.GibiByte)
CORE_SIZE = Size(256, Unit.MebiByte)
NUM_CORES = 4


def _write_random(target_path: str, tag: str, size: Size = CORE_SIZE):
    """Generate a fresh random buffer (tag identifies the temp file) and write it."""
    src = f"/tmp/cas_disconnect_{tag}"
    mb = int(size.get_value(Unit.MebiByte))
    TestRun.executor.run_expect_success(
        f"dd if=/dev/urandom of={src} bs=1M count={mb} iflag=fullblock"
    )
    TestRun.executor.run_expect_success(
        f"dd if={src} of={target_path} bs=1M count={mb} oflag=direct conv=fdatasync"
    )


def _is_queue_frozen(exp_obj_path: str, timeout_s: int = 3) -> bool:
    """Issue a small read on the exported object and check that it blocks."""
    def _do_io():
        return TestRun.executor.run(
            f"dd if={exp_obj_path} of=/dev/null bs=4k count=1 iflag=direct"
        )

    task = start_async_func(_do_io)
    time.sleep(timeout_s)
    if task.done():
        # I/O completed - queue is not frozen
        return False
    # Still pending - the I/O will complete once the queue is unfrozen.
    return True


def _prepare_devices():
    cache_dev = TestRun.disks["cache"]
    core_dev = TestRun.disks["core"]
    cache_dev.create_partitions([CACHE_SIZE])
    core_dev.create_partitions([CORE_SIZE] * NUM_CORES)
    return cache_dev.partitions[0], core_dev.partitions[:NUM_CORES]


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_disconnect_default():
    """
        title: Disconnect cache with default flags
        description: |
            Disconnect WB cache without extra flags. Cache should be flushed and exported
            object queues frozen. After connect data should be intact and cache clean.
        pass_criteria:
          - exported object queues are frozen after disconnect
          - cache contains no dirty data after connect
          - core data is consistent after connect
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]

    with TestRun.step("Write data to each exported object"):
        for i, core in enumerate(cores):
            _write_random(core.path, tag=f"core{i}")
        sync()
        crc_before = [crc32sum(core.path) for core in cores]

    with TestRun.step("Disconnect cache (default flags)"):
        casadm.disconnect_cache(cache.cache_id)

    with TestRun.step("Verify exported object queues are frozen"):
        for core in cores:
            if not _is_queue_frozen(core.path):
                TestRun.fail(f"Exported object {core.path} queue is not frozen.")

    with TestRun.step("Connect cache"):
        cache = casadm.connect_cache(cache_part)

    with TestRun.step("Verify cache is clean"):
        dirty = cache.get_dirty_blocks()
        if dirty.get_value() != 0:
            TestRun.fail(f"Cache should be clean after default disconnect, dirty={dirty}")

    with TestRun.step("Verify data on each core is consistent"):
        for core, expected in zip(cache.get_cores(), crc_before):
            actual = crc32sum(core.path)
            if actual != expected:
                TestRun.fail(
                    f"Data mismatch on {core.path}: expected {expected}, got {actual}"
                )

    with TestRun.step("Stop cache"):
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_disconnect_no_flush():
    """
        title: Disconnect cache with --no-flush
        description: |
            Disconnect WB cache without flushing dirty data. Cache should retain dirty
            blocks and exported object queues should be frozen. After connect data
            must remain consistent.
        pass_criteria:
          - exported object queues are frozen after disconnect
          - cache contains dirty data after connect
          - core data accessed via exported object is consistent after connect
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]

    with TestRun.step("Write data to each exported object"):
        for i, core in enumerate(cores):
            _write_random(core.path, tag=f"core{i}")
        sync()
        crc_before = [crc32sum(core.path) for core in cores]

    with TestRun.step("Verify cache has dirty data"):
        if cache.get_dirty_blocks().get_value() == 0:
            TestRun.fail("Cache should contain dirty data before disconnect in WB mode.")

    with TestRun.step("Disconnect cache with --no-flush"):
        casadm.disconnect_cache(cache.cache_id, no_flush=True)

    with TestRun.step("Verify exported object queues are frozen"):
        for core in cores:
            if not _is_queue_frozen(core.path):
                TestRun.fail(f"Exported object {core.path} queue is not frozen.")

    with TestRun.step("Connect cache"):
        cache = casadm.connect_cache(cache_part)

    with TestRun.step("Verify cache is dirty"):
        if cache.get_dirty_blocks().get_value() == 0:
            TestRun.fail("Cache should contain dirty data after --no-flush disconnect.")

    with TestRun.step("Verify data on each core is consistent"):
        for core, expected in zip(cache.get_cores(), crc_before):
            actual = crc32sum(core.path)
            if actual != expected:
                TestRun.fail(
                    f"Data mismatch on {core.path}: expected {expected}, got {actual}"
                )

    with TestRun.step("Stop cache"):
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_disconnect_pt():
    """
        title: Disconnect cache with --pass-through
        description: |
            Disconnect WB cache in pass-through mode. Exported objects must still serve
            I/O directly to core. Overwriting half of the data must succeed and remain
            consistent after reconnect with a clean cache.
        pass_criteria:
          - exported object queues are not frozen and serve I/O after disconnect
          - cache contains no dirty data after connect
          - core data is consistent (including the overwritten half) after connect
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]

    with TestRun.step("Write data to each exported object"):
        for i, core in enumerate(cores):
            _write_random(core.path, tag=f"core{i}")
        sync()

    with TestRun.step("Disconnect cache with --pass-through"):
        casadm.disconnect_cache(cache.cache_id, pass_through=True)

    with TestRun.step("Verify exported object queues are not frozen and serve I/O"):
        for core in cores:
            if _is_queue_frozen(core.path, timeout_s=2):
                TestRun.fail(
                    f"Exported object {core.path} queue should not be frozen in pass-through."
                )

    with TestRun.step("Overwrite the second half of the data on each core via the exported object"):
        half_mb = int(CORE_SIZE.get_value(Unit.MebiByte) / 2)
        for i, core in enumerate(cores):
            src = f"/tmp/cas_disconnect_overwrite_{i}"
            TestRun.executor.run_expect_success(
                f"dd if=/dev/urandom of={src} bs=1M count={half_mb} iflag=fullblock"
            )
            TestRun.executor.run_expect_success(
                f"dd if={src} of={core.path} bs=1M count={half_mb} seek={half_mb} "
                f"oflag=direct conv=fdatasync"
            )
        sync()
        crc_expected = [crc32sum(core.path) for core in cores]

    with TestRun.step("Connect cache"):
        cache = casadm.connect_cache(cache_part)

    with TestRun.step("Verify cache is clean"):
        dirty = cache.get_dirty_blocks()
        if dirty.get_value() != 0:
            TestRun.fail(f"Cache should be clean after pass-through disconnect, dirty={dirty}")

    with TestRun.step("Verify data on each core is consistent"):
        for core, expected in zip(cache.get_cores(), crc_expected):
            actual = crc32sum(core.path)
            if actual != expected:
                TestRun.fail(
                    f"Data mismatch on {core.path}: expected {expected}, got {actual}"
                )

    with TestRun.step("Stop cache"):
        cache.stop()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("disconnect_mode", ["default", "no-flush", "pass-through"])
def test_disconnect_stress(disconnect_mode):
    """
        title: Stress test of cache disconnect/connect under heavy IO
        description: |
            Run mixed random read/write fio workload on multiple cores while repeatedly
            disconnecting and connecting the cache. Each disconnect/connect operation
            must complete within a fixed timeout.
        pass_criteria:
          - All disconnect operations complete within the timeout.
          - All connect operations complete within the timeout.
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]
        cache_id = cache.cache_id

    fio_pid = None
    try:
        with TestRun.step("Start asynchronous fio workload on all cores"):
            fio = Fio().create_command()
            fio.io_engine(IoEngine.libaio) \
                .read_write(ReadWrite.randrw) \
                .write_percentage(50) \
                .io_depth(64) \
                .direct() \
                .time_based() \
                .run_time(timedelta(hours=2)) \
                .num_jobs(2)
            for i, core in enumerate(cores):
                for bs in [Size(4, Unit.KibiByte), Size(64, Unit.KibiByte),
                           Size(1, Unit.MebiByte)]:
                    bs_label = int(bs.get_value(Unit.KibiByte))
                    job = fio.add_job(f"core{i}_bs{bs_label}k")
                    job.target(core.path).block_size(bs)
            fio_pid = fio.run_in_background()

        op_timeout = timedelta(seconds=300)
        pass_through = (disconnect_mode == "pass-through")
        no_flush = (disconnect_mode == "no-flush")

        with TestRun.step(f"Loop 100 disconnect ({disconnect_mode}) / connect iterations"):
            for i in range(100):
                TestRun.LOGGER.info(f"Stress iteration {i + 1}/100")
                time.sleep(10)

                output = TestRun.executor.run(
                    script_disconnect_cache_cmd(
                        str(cache_id), pass_through=pass_through, no_flush=no_flush
                    ),
                    timeout=op_timeout,
                )
                if output.exit_code != 0:
                    TestRun.fail(
                        f"Disconnect failed at iteration {i + 1} "
                        f"(stderr: {output.stderr})"
                    )

                time.sleep(10)

                output = TestRun.executor.run(
                    script_connect_cache_cmd(cache_part.path),
                    timeout=op_timeout,
                )
                if output.exit_code != 0:
                    TestRun.fail(
                        f"Connect failed at iteration {i + 1} "
                        f"(stderr: {output.stderr})"
                    )
    finally:
        with TestRun.step("Stop fio"):
            if fio_pid is not None:
                TestRun.executor.kill_process(fio_pid)

        with TestRun.step("Stop cache"):
            casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("disconnect_mode", ["default", "no-flush", "pass-through"])
@pytest.mark.parametrize("wait_seconds", [10, 30, 60, 120])
def test_disconnect_wait(disconnect_mode, wait_seconds):
    """
        title: Disconnect cache and wait before reconnecting under IO
        description: |
            Run mixed random read/write fio workload on multiple cores, disconnect the
            cache, wait a parametrized amount of time, then reconnect. Disconnect and
            connect operations must each complete within a fixed timeout.
        pass_criteria:
          - Disconnect operation completes within the timeout.
          - Connect operation completes within the timeout.
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]
        cache_id = cache.cache_id

    fio_pid = None
    try:
        with TestRun.step("Start asynchronous fio workload on all cores"):
            fio = Fio().create_command()
            fio.io_engine(IoEngine.libaio) \
                .read_write(ReadWrite.randrw) \
                .write_percentage(50) \
                .io_depth(64) \
                .direct() \
                .time_based() \
                .run_time(timedelta(hours=1)) \
                .num_jobs(2)
            for i, core in enumerate(cores):
                for bs in [Size(4, Unit.KibiByte), Size(64, Unit.KibiByte),
                           Size(1, Unit.MebiByte)]:
                    bs_label = int(bs.get_value(Unit.KibiByte))
                    job = fio.add_job(f"core{i}_bs{bs_label}k")
                    job.target(core.path).block_size(bs)
            fio_pid = fio.run_in_background()

        op_timeout = timedelta(seconds=300)
        pass_through = (disconnect_mode == "pass-through")
        no_flush = (disconnect_mode == "no-flush")

        with TestRun.step("Let fio warm up"):
            time.sleep(10)

        with TestRun.step(f"Disconnect cache ({disconnect_mode})"):
            output = TestRun.executor.run(
                script_disconnect_cache_cmd(
                    str(cache_id), pass_through=pass_through, no_flush=no_flush
                ),
                timeout=op_timeout,
            )
            if output.exit_code != 0:
                TestRun.fail(f"Disconnect failed (stderr: {output.stderr})")

        with TestRun.step(f"Wait {wait_seconds}s before reconnect"):
            time.sleep(wait_seconds)

        with TestRun.step("Connect cache"):
            output = TestRun.executor.run(
                script_connect_cache_cmd(cache_part.path),
                timeout=op_timeout,
            )
            if output.exit_code != 0:
                TestRun.fail(f"Connect failed (stderr: {output.stderr})")
    finally:
        with TestRun.step("Stop fio"):
            if fio_pid is not None:
                TestRun.executor.kill_process(fio_pid)

        with TestRun.step("Stop cache"):
            casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("disconnect_mode", ["default", "no-flush", "pass-through"])
def test_disconnect_delete(disconnect_mode):
    """
        title: Delete exported objects after disconnect, then load cache
        description: |
            After cache disconnect, delete each exported object via cas_bd sysfs interface.
            Then load the cache normally and verify that the data on cores is consistent.
        pass_criteria:
          - exported objects can be deleted after disconnect
          - cache loads successfully
          - core data is consistent after load
    """
    with TestRun.step("Prepare devices"):
        cache_part, core_parts = _prepare_devices()

    with TestRun.step(f"Start WB cache and add {NUM_CORES} cores"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        cores = [cache.add_core(c) for c in core_parts]
        cache_id = cache.cache_id
        dev_names = [f"cas{cache_id}-{core.core_id}" for core in cores]
        core_device_paths = [core.core_device.path for core in cores]

    with TestRun.step("Write data to each exported object"):
        for i, core in enumerate(cores):
            _write_random(core.path, tag=f"core{i}")
        sync()
        crc_before = [crc32sum(core.path) for core in cores]

    with TestRun.step(f"Disconnect cache ({disconnect_mode})"):
        casadm.disconnect_cache(
            cache_id,
            pass_through=(disconnect_mode == "pass-through"),
            no_flush=(disconnect_mode == "no-flush"),
        )

    with TestRun.step("Delete each exported object via cas_bd sysfs"):
        for name in dev_names:
            TestRun.executor.run_expect_success(
                f"echo {name} > /sys/module/cas_bd/delete"
            )

    with TestRun.step("Verify exported objects are gone"):
        for name in dev_names:
            TestRun.executor.run_expect_fail(f"test -e /dev/{name}")

    with TestRun.step("Load cache"):
        cache = casadm.load_cache(cache_part)

    with TestRun.step("Verify data on each core is consistent"):
        loaded_cores = sorted(cache.get_cores(), key=lambda c: c.core_id)
        for core, src_path, expected in zip(loaded_cores, core_device_paths, crc_before):
            if core.core_device.path != src_path:
                TestRun.fail(
                    f"Loaded core {core.core_id} points to {core.core_device.path}, "
                    f"expected {src_path}"
                )
            actual = crc32sum(core.path)
            if actual != expected:
                TestRun.fail(
                    f"Data mismatch on {core.path}: expected {expected}, got {actual}"
                )

    with TestRun.step("Stop cache"):
        cache.stop()
