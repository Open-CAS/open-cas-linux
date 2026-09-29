#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import time
from collections import namedtuple
from datetime import timedelta

import pytest

from api.cas import casadm
from api.cas.cache_config import CacheMode, CacheStatus
from api.cas.installer import clean_opencas_repo, rsync_opencas_sources
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_tools import remove
from type_def.size import Size, Unit


# Each variant is a separate copy of the sources, built once per test module
# and reused by its tests. Caches only load under the MAIN.MAJOR.MINOR that
# created them, so 'next' stays within the release and is made newer by its
# build number instead, which './configure' derives from git history. That
# makes installing 'next' over 'current' an upgrade and the other way around
# a downgrade.
upgrade_root = "/var/tmp/cas_make_upgrade_test"
variants = {
    "current": None,
    "next": "9999",
}
directions = {
    "upgrade": ("current", "next"),
    "downgrade": ("next", "current"),
}
disconnect_modes = {
    "default": {},
    "no-flush": {"no_flush": True},
    "pass-through": {"pass_through": True},
}

# Shell expressions, to be used inside commands
modules_dir = "/lib/modules/$(uname -r)/extra/block/opencas"
fallback_dir = "/lib/opencas/fallback/$(uname -r)"
installed_symvers = f"{modules_dir}/cas_bd.symvers"

config_file = "/etc/opencas/opencas.conf"
config_marker = "# make upgrade test marker"

# Checksums of every installed CAS file, to tell whether anything changed
installed_files_checksums = (
    f"find {modules_dir} /lib/opencas /usr/lib/opencas /etc/opencas /usr/sbin/casadm "
    f"/var/lib/opencas -type f -exec md5sum {{}} + 2>/dev/null | sort"
)

data_file = "/var/tmp/cas_make_upgrade_data"
fio_log = "/var/tmp/cas_make_upgrade_fio.log"

CACHE_SIZE = Size(4, Unit.GibiByte)
CORE_SIZE = Size(512, Unit.MebiByte)

build_timeout = timedelta(minutes=30)

Variant = namedtuple("Variant", ["path", "version"])


@pytest.fixture(scope="module", autouse=True)
def fresh_builds():
    """Variants are built once for the whole module, from the sources under test."""
    rsync_opencas_sources()
    clean_opencas_repo()
    remove(upgrade_root, recursive=True, force=True, ignore_errors=True)
    yield


@pytest.fixture(autouse=True)
def installation_restored():
    """Whatever a test leaves installed, hand the next one a regular installation."""
    yield
    restore_installation()


@pytest.mark.parametrize("direction", directions.keys())
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_make_upgrade(direction):
    """
    title: Upgrade and downgrade from sources with 'make upgrade'.
    description: |
      Install one version, stop a cache holding dirty data, switch to the other
      version with 'make upgrade' and load the cache again. The new cas_cache
      has to be running on top of the cas_bd of the version replaced.
    pass_criteria:
      - make upgrade succeeds
      - the new version is installed, including casadm
      - the loaded cas_cache is the new one, the loaded cas_bd the old one
      - the fallback modules and symvers are installed
      - user configuration and enabled services are preserved
      - the cache loads with its dirty data and the core data is intact
    """
    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions[direction])

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")
        TestRun.executor.run_expect_success(f"echo '{config_marker}' >> {config_file}")

    with TestRun.step("Start a WB cache and write data to its core"):
        cache_dev, core_dev = TestRun.disks["cache"], TestRun.disks["core"]
        cache_dev.create_partitions([CACHE_SIZE])
        core_dev.create_partitions([CORE_SIZE])
        cache_part = cache_dev.partitions[0]

        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        core = cache.add_core(core_dev.partitions[0])
        TestRun.executor.run_expect_success(
            f"head -c {int(CORE_SIZE.get_value())} /dev/urandom > {data_file}"
        )
        TestRun.executor.run_expect_success(f"dd if={data_file} of={core.path} bs=1M conv=fsync")

        if cache.get_dirty_blocks().get_value() == 0:
            TestRun.fail("Cache holds no dirty data to carry across the upgrade")

    with TestRun.step("Stop the cache without flushing"):
        cache.stop(no_data_flush=True)

    with TestRun.step(f"Build the fallback cas_cache of {new.version}"):
        TestRun.executor.run_expect_success(
            f"cd {new.path} && make -j$(nproc) FALLBACK_SYMVERS={installed_symvers}",
            build_timeout,
        )

    with TestRun.step(f"Upgrade to {new.version}"):
        TestRun.executor.run_expect_success(f"cd {new.path} && make upgrade", build_timeout)

    with TestRun.step("Check the installation"):
        check_upgraded(old, new)

    with TestRun.step("Load the cache"):
        cache = casadm.load_cache(cache_part)

        if cache.get_dirty_blocks().get_value() == 0:
            TestRun.fail("Dirty data was lost across the upgrade")

    with TestRun.step("Check the core data"):
        TestRun.executor.run_expect_success("echo 3 > /proc/sys/vm/drop_caches")
        TestRun.executor.run_expect_success(
            f"cmp -n {int(CORE_SIZE.get_value())} {data_file} {core.path}"
        )

    with TestRun.step("Stop the cache"):
        cache.stop()


@pytest.mark.parametrize("disconnect_mode", disconnect_modes.keys())
@pytest.mark.parametrize("direction", directions.keys())
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_make_upgrade_under_io(direction, disconnect_mode):
    """
    title: In-flight upgrade and downgrade with 'make upgrade' under I/O.
    description: |
      Disconnect a running WB cache while I/O keeps being issued to its
      exported objects, replace CAS with 'make upgrade', and connect the
      cache with the new cas_cache running on top of the old cas_bd.
    pass_criteria:
      - make upgrade succeeds with the cache disconnected
      - the loaded cas_cache is the new one, the loaded cas_bd the old one
      - the cache connects with the new version
      - I/O issued throughout reads back what it wrote
      - dirty data is kept when disconnecting without flush, flushed otherwise
      - the core data is intact
    """
    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions[direction])

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")
        TestRun.executor.run_expect_success(f"echo '{config_marker}' >> {config_file}")

    with TestRun.step(f"Build the fallback cas_cache of {new.version}"):
        TestRun.executor.run_expect_success(
            f"cd {new.path} && make -j$(nproc) FALLBACK_SYMVERS={installed_symvers}",
            build_timeout,
        )

    with TestRun.step("Start a WB cache with two cores"):
        cache_dev, core_dev = TestRun.disks["cache"], TestRun.disks["core"]
        cache_dev.create_partitions([CACHE_SIZE])
        core_dev.create_partitions([CORE_SIZE] * 2)
        cache_part = cache_dev.partitions[0]

        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
        data_core, io_core = [cache.add_core(part) for part in core_dev.partitions]

    with TestRun.step("Write data to the first core"):
        TestRun.executor.run_expect_success(
            f"head -c {int(CORE_SIZE.get_value())} /dev/urandom > {data_file}"
        )
        TestRun.executor.run_expect_success(
            f"dd if={data_file} of={data_core.path} bs=1M conv=fsync"
        )

    with TestRun.step("Start verified I/O on the second core"):
        fio_pid = TestRun.executor.run_in_background(
            f"fio --name=live --filename={io_core.path} --rw=randrw --bs=4k --direct=1 "
            f"--ioengine=libaio --iodepth=8 --verify=crc32c --verify_backlog=1024 "
            f"--verify_fatal=1 --verify_state_save=0 --time_based --runtime=7200",
            stdout_redirect_path=fio_log,
            stderr_redirect_path=fio_log,
        )
        time.sleep(10)

    with TestRun.step(f"Disconnect the cache ({disconnect_mode})"):
        casadm.disconnect_cache(cache.cache_id, **disconnect_modes[disconnect_mode])

    with TestRun.step(f"Upgrade to {new.version}"):
        TestRun.executor.run_expect_success(f"cd {new.path} && make upgrade", build_timeout)

    with TestRun.step("Connect the cache"):
        cache = casadm.connect_cache(cache_part)

    with TestRun.step("Stop the I/O"):
        time.sleep(10)
        TestRun.executor.run(f"kill -INT {fio_pid}")
        TestRun.executor.wait_cmd_finish(fio_pid)
        TestRun.executor.run_expect_success(f"grep -q 'err= 0' {fio_log}")

    with TestRun.step("Check the installation"):
        check_upgraded(old, new)

    with TestRun.step("Check the dirty data of the first core"):
        # the second core keeps getting new dirty data, the first one does not
        dirty = data_core.get_dirty_blocks().get_value()
        if disconnect_mode == "no-flush" and dirty == 0:
            TestRun.fail("Dirty data was lost across the upgrade")
        if disconnect_mode != "no-flush" and dirty != 0:
            TestRun.fail(f"Dirty data was not flushed on disconnect: {dirty}")

    with TestRun.step("Check the data of the first core"):
        TestRun.executor.run_expect_success("echo 3 > /proc/sys/vm/drop_caches")
        TestRun.executor.run_expect_success(
            f"cmp -n {int(CORE_SIZE.get_value())} {data_file} {data_core.path}"
        )

    with TestRun.step("Stop the cache"):
        cache.stop()


@pytest.mark.parametrize("direction", directions.keys())
def test_make_upgrade_fallback_not_built(direction):
    """
    title: 'make upgrade' requires the fallback cas_cache.
    description: |
      Run 'make upgrade' from sources built the regular way, without the
      fallback cas_cache for the loaded cas_bd.
    pass_criteria:
      - make upgrade fails asking to build the fallback
      - installed files and loaded modules are left as they were
    """
    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions[direction])
        TestRun.executor.run_expect_success(f"rm -rf {new.path}/modules/.fallback")

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")
        files_before = TestRun.executor.run(installed_files_checksums).stdout

    with TestRun.step(f"Upgrade to {new.version}"):
        output = TestRun.executor.run(f"cd {new.path} && make upgrade")
        if output.exit_code == 0 or "Fallback cas_cache.ko not built" not in output.stderr:
            TestRun.fail(
                f"make upgrade was not refused as expected:\n{output.stdout}\n{output.stderr}"
            )

    with TestRun.step("Check nothing changed"):
        check_not_upgraded(old, new, files_before)
        TestRun.executor.run_expect_success(
            f'test "$(cat /sys/module/cas_cache/version /sys/module/cas_bd/version | sort -u)" '
            f"= '{old.version}'"
        )


def test_make_upgrade_fallback_mismatch():
    """
    title: 'make upgrade' requires the fallback built for the loaded cas_bd.
    description: |
      Build the fallback cas_cache against symvers that do not match the loaded
      cas_bd and run 'make upgrade'.
    pass_criteria:
      - make upgrade fails before changing anything
      - installed files and loaded modules are left as they were
    """
    foreign_symvers = "/var/tmp/cas_make_upgrade_foreign.symvers"

    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions["upgrade"])

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")
        files_before = TestRun.executor.run(installed_files_checksums).stdout

    with TestRun.step(f"Build the fallback cas_cache of {new.version} for a different cas_bd"):
        TestRun.executor.run_expect_success(
            f"sed '1s/^0x[0-9a-f]*/0xdeadbeef/' {installed_symvers} > {foreign_symvers}"
        )
        TestRun.executor.run_expect_success(
            f"cd {new.path} && make -j$(nproc) FALLBACK_SYMVERS={foreign_symvers}",
            build_timeout,
        )

    with TestRun.step(f"Upgrade to {new.version}"):
        output = TestRun.executor.run(f"cd {new.path} && make upgrade")
        if output.exit_code == 0 or "was not built against the loaded" not in output.stderr:
            TestRun.fail(
                f"make upgrade was not refused as expected:\n{output.stdout}\n{output.stderr}"
            )

    with TestRun.step("Check nothing changed"):
        check_not_upgraded(old, new, files_before)
        TestRun.executor.run_expect_success(
            f'test "$(cat /sys/module/cas_cache/version /sys/module/cas_bd/version | sort -u)" '
            f"= '{old.version}'"
        )


@pytest.mark.parametrize(
    "unloaded, expected_error",
    [
        ("cas_cache", "Module cas_cache is not currently loaded"),
        ("cas_cache cas_bd", "cas_bd not loaded"),
    ],
)
def test_make_upgrade_modules_not_loaded(unloaded, expected_error):
    """
    title: 'make upgrade' requires the old modules to be loaded.
    description: |
      Unload cas_cache, or both CAS modules, and run 'make upgrade'. Without
      cas_cache there is nothing to replace, and without cas_bd nothing to
      load the fallback cas_cache on top of.
    pass_criteria:
      - make upgrade fails before changing anything
      - installed files are left as they were, and no module gets loaded
    """
    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions["upgrade"])

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")

    with TestRun.step(f"Build the fallback cas_cache of {new.version}"):
        TestRun.executor.run_expect_success(
            f"cd {new.path} && make -j$(nproc) FALLBACK_SYMVERS={installed_symvers}",
            build_timeout,
        )

    with TestRun.step(f"Unload {unloaded}"):
        TestRun.executor.run_expect_success(f"rmmod {unloaded}")
        files_before = TestRun.executor.run(installed_files_checksums).stdout

    with TestRun.step(f"Upgrade to {new.version}"):
        output = TestRun.executor.run(f"cd {new.path} && make upgrade")
        if output.exit_code == 0 or expected_error not in output.stderr:
            TestRun.fail(
                f"make upgrade was not refused as expected:\n{output.stdout}\n{output.stderr}"
            )

    with TestRun.step("Check nothing changed"):
        check_not_upgraded(old, new, files_before)
        for module in unloaded.split():
            if TestRun.executor.run(f"test -e /sys/module/{module}").exit_code == 0:
                TestRun.fail(f"{module} got loaded by a refused upgrade")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.nand, DiskType.optane]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_make_upgrade_cache_running():
    """
    title: 'make upgrade' does not touch running caches.
    description: |
      Run 'make upgrade' while a cache is running. cas_cache cannot be
      unloaded then, so the upgrade has to stop before changing anything.
    pass_criteria:
      - make upgrade fails before changing anything
      - installed files and loaded modules are left as they were
      - the cache keeps running with its dirty data and the core data is intact
    """
    with TestRun.step("Build both versions"):
        old, new = (build_variant(name) for name in directions["upgrade"])

    with TestRun.step(f"Install {old.version}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(f"cd {old.path} && make install")

    with TestRun.step(f"Build the fallback cas_cache of {new.version}"):
        TestRun.executor.run_expect_success(
            f"cd {new.path} && make -j$(nproc) FALLBACK_SYMVERS={installed_symvers}",
            build_timeout,
        )

    with TestRun.step("Start a WB cache and write data to its core"):
        cache_dev, core_dev = TestRun.disks["cache"], TestRun.disks["core"]
        cache_dev.create_partitions([CACHE_SIZE])
        core_dev.create_partitions([CORE_SIZE])

        cache = casadm.start_cache(cache_dev.partitions[0], cache_mode=CacheMode.WB, force=True)
        core = cache.add_core(core_dev.partitions[0])
        TestRun.executor.run_expect_success(
            f"head -c {int(CORE_SIZE.get_value())} /dev/urandom > {data_file}"
        )
        TestRun.executor.run_expect_success(f"dd if={data_file} of={core.path} bs=1M conv=fsync")
        files_before = TestRun.executor.run(installed_files_checksums).stdout

    with TestRun.step(f"Upgrade to {new.version}"):
        output = TestRun.executor.run(f"cd {new.path} && make upgrade")
        if output.exit_code == 0 or "Module cas_cache is in use" not in output.stderr:
            TestRun.fail(
                f"make upgrade was not refused as expected:\n{output.stdout}\n{output.stderr}"
            )

    with TestRun.step("Check nothing changed"):
        check_not_upgraded(old, new, files_before)
        TestRun.executor.run_expect_success(
            f'test "$(cat /sys/module/cas_cache/version /sys/module/cas_bd/version | sort -u)" '
            f"= '{old.version}'"
        )

    with TestRun.step("Check the cache"):
        if cache.get_status() != CacheStatus.running:
            TestRun.fail(f"Cache is {cache.get_status()} after the refused upgrade")
        if cache.get_dirty_blocks().get_value() == 0:
            TestRun.fail("Cache lost its dirty data")

        TestRun.executor.run_expect_success("echo 3 > /proc/sys/vm/drop_caches")
        TestRun.executor.run_expect_success(
            f"cmp -n {int(CORE_SIZE.get_value())} {data_file} {core.path}"
        )

    with TestRun.step("Stop the cache"):
        cache.stop()


def build_variant(name: str):
    """Build a variant with the regular build, unless an earlier test did."""
    path = os.path.join(upgrade_root, name)

    if TestRun.executor.run(f"test -f {path}/modules/cas_cache/cas_cache.ko").exit_code != 0:
        TestRun.LOGGER.info(f"Building the {name} variant in {path}")
        remove(path, recursive=True, force=True, ignore_errors=True)
        TestRun.executor.run_expect_success(
            f"mkdir -p {path} && tar -C {TestRun.usr.working_dir} --exclude=./test -cf - . "
            f"| tar -C {path} --no-same-owner -xf -"
        )
        TestRun.executor.run_expect_success(f"cd {path} && ./configure", build_timeout)

        build = variants[name]
        if build:
            TestRun.executor.run_expect_success(
                f"sed -i -e 's/^CAS_VERSION_BUILD=.*/CAS_VERSION_BUILD={build}/' "
                f"-e 's/^\\(CAS_VERSION=[0-9]*\\.[0-9]*\\.[0-9]*\\.\\)[0-9]*/\\1{build}/' "
                f"{path}/.metadata/cas_version"
            )

        TestRun.executor.run_expect_success(f"cd {path} && make -j$(nproc)", build_timeout)

    version = TestRun.executor.run_expect_success(
        f"sed -n 's/^CAS_VERSION=//p' {path}/.metadata/cas_version"
    ).stdout.strip()
    return Variant(path, version)


def check_upgraded(old: Variant, new: Variant):
    """State after a successful upgrade: new files, fallback cas_cache on the old cas_bd."""
    expected = {
        "cat /sys/module/cas_cache/version": new.version,
        "cat /sys/module/cas_bd/version": old.version,
        f"modinfo -F version {modules_dir}/cas_cache.ko": new.version,
        f"modinfo -F version {modules_dir}/cas_bd.ko": new.version,
        f"modinfo -F version {fallback_dir}/cas_cache.ko": new.version,
        f"modinfo -F version {fallback_dir}/cas_bd.ko": old.version,
        "casadm -V -o csv | sed -n 's/^CAS CLI Utility,//p'": new.version,
    }
    for command, version in expected.items():
        actual = TestRun.executor.run(command).stdout.strip()
        if actual != version:
            TestRun.fail(f"'{command}' reports {actual}, expected {version}")

    TestRun.executor.run_expect_success(f"test -f {fallback_dir}/cas_bd.symvers")
    TestRun.executor.run_expect_success(f"grep -qxF '{config_marker}' {config_file}")
    TestRun.executor.run_expect_success(
        "systemctl is-enabled --quiet open-cas.service open-cas-shutdown.service"
    )
    TestRun.executor.run_expect_success(f"test ! -e {new.path}/.upgrade")

    # udev has to be processing events again
    TestRun.executor.run("udevadm trigger --action=change /sys/class/mem/null")
    TestRun.executor.run_expect_success("udevadm settle --timeout=10")


def check_not_upgraded(old: Variant, new: Variant, files_before: str):
    """A refused upgrade must leave the installation as it was."""
    if TestRun.executor.run(installed_files_checksums).stdout != files_before:
        TestRun.fail("A refused upgrade changed the installed files")

    TestRun.executor.run_expect_success(
        f"modinfo -F version {modules_dir}/cas_cache.ko | grep -qx '{old.version}'"
    )
    TestRun.executor.run_expect_success(f"test ! -e {new.path}/.upgrade")

    # udev has to be processing events again
    TestRun.executor.run("udevadm trigger --action=change /sys/class/mem/null")
    TestRun.executor.run_expect_success("udevadm settle --timeout=10")


def restore_installation():
    """Leave the DUT with the sources under test installed the regular way."""
    TestRun.executor.run("pkill -KILL -x fio")
    TestRun.executor.run("udevadm control --start-exec-queue")
    try:
        casadm.stop_all_caches()
    except Exception as e:
        TestRun.LOGGER.warning(f"Failed to stop caches: {e}")

    # exported objects of disconnected caches stay with cas_bd
    TestRun.executor.run(
        "test -e /sys/module/cas_bd/delete && for dev in $(ls /dev | grep '^cas[0-9]'); do "
        "echo $dev > /sys/module/cas_bd/delete; done"
    )
    TestRun.executor.run(f"rmmod cas_cache; rmmod cas_bd; rm -rf {fallback_dir}")
    TestRun.executor.run(f"rm -f {data_file} {fio_log} /var/tmp/cas_make_upgrade_foreign.symvers")

    current = os.path.join(upgrade_root, "current")
    if TestRun.executor.run(f"test -f {current}/modules/cas_cache/cas_cache.ko").exit_code == 0:
        output = TestRun.executor.run(f"cd {current} && rm -rf .upgrade && make install")
        if output.exit_code != 0:
            TestRun.LOGGER.error(f"Failed to reinstall CAS:\n{output.stdout}\n{output.stderr}")
