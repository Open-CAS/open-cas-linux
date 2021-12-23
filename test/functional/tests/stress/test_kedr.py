#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from datetime import timedelta

from test_tools.kedr import Kedr, KedrProfile
from api.cas import cas_module, installer, casadm
from core.test_run import TestRun
from test_utils import os_utils
from test_utils.size import Size, Unit
from test_tools.disk_utils import Filesystem
from test_utils.os_utils import sync
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan

mountpoint = "/tmp/cas1-1"

@pytest.fixture(scope="module")
def install_kedr():
    TestRun.LOGGER.info("Checking if kedr is installed")
    if not Kedr.is_installed():
        TestRun.LOGGER.info("Installing kedr")
        Kedr.install()


@pytest.fixture(scope="function")
def unload_modules():
    TestRun.LOGGER.info("Check if CAS is installed")
    if installer.check_if_installed():
        TestRun.LOGGER.info("Unloading modules")
        cas_module.unload_all_cas_modules()

    TestRun.LOGGER.info("Stop kedr if it is running")
    if Kedr.is_loaded():
        Kedr.stop()

    TestRun.LOGGER.info("Mounting debugfs")
    os_utils.mount_debugfs()


@pytest.mark.parametrize("module", cas_module.CasModule)
def test_kedr_memleak_load_cas_module(module, unload_modules, install_kedr):
    """
    title: Loading modules with kedr started with 'memleak' configuration
    description: Load and unload modules with kedr started to watch for memory leaks
    pass_criteria:
      - No memory leaks observed after loading and unloading module
    """
    with TestRun.step(f"Starting kedr against {module}"):
        Kedr.start(module.value)

    with TestRun.step(f"Loading {module}"):
        os_utils.load_kernel_module(module.value)

    with TestRun.step(f"Unloading {module}"):
        os_utils.unload_kernel_module(module.value, os_utils.ModuleRemoveMethod.modprobe)

    with TestRun.step(f"Checking for memory leaks for {module}"):
        try:
            Kedr.check_for_mem_leaks(module.value)
        except Exception as e:
            TestRun.LOGGER.error(f"{e}")

    with TestRun.step(f"Stopping kedr"):
        Kedr.stop()


@pytest.mark.parametrize("module", cas_module.CasModule)
def test_kedr_fsim_load_cas_module(module, unload_modules, install_kedr):
    """
    title: Loading modules with kedr started with 'fsim' configuration
    description: Load and unload modules with kedr started to simulate kmalloc fails
    pass_criteria:
      - Module fails to load
    """
    with TestRun.step(f"Starting kedr against {module}"):
        Kedr.start(module.value, KedrProfile.FAULT_SIM)

    with TestRun.step("Setting up fault simulation parameters"):
        Kedr.setup_fault_injections()

    with TestRun.step(f"Trying to load {module}"):
        out = os_utils.load_kernel_module(module.value)
        if out.exit_code == 0 \
                or "Cannot allocate memory" not in out.stderr:
            TestRun.LOGGER.error(f"Loading module should fail because of alloc error, instead "
                                 f"modprobe's output is: {out}")

    with TestRun.step(f"Stopping kedr"):
        Kedr.stop()


@pytest.mark.parametrize("module", cas_module.CasModule)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_kedr_start_cache(module, unload_modules, install_kedr):
    """
    title: Start cache and add core with kedr started against one of CAS modules
    description: |
        Load CAS modules, start kedr against one of them, start cache and add core,
        stop cache and unload modules
    pass_criteria:
      - No memory leaks observed
    """
    with TestRun.step("Preparing cache device"):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_part = cache_device.partitions[0]

    with TestRun.step("Preparing core device"):
        core_device = TestRun.disks['core']
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        core_part = core_device.partitions[0]

    with TestRun.step("Unload CAS modules if needed"):
        if os_utils.is_kernel_module_loaded(module.value):
            cas_module.unload_all_cas_modules()

    with TestRun.step(f"Starting kedr against {module.value}"):
        Kedr.start(module.value)

    with TestRun.step(f"Loading CAS modules"):
        os_utils.load_kernel_module(cas_module.CasModule.cache.value)

    with TestRun.step("Starting cache"):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Adding core"):
        cache.add_core(core_dev=core_part)

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step(f"Unloading CAS modules"):
        cas_module.unload_all_cas_modules()

    with TestRun.step(f"Checking for memory leaks for {module}"):
        try:
            Kedr.check_for_mem_leaks(module.value)
        except Exception as e:
            TestRun.LOGGER.error(f"{e}")

    with TestRun.step(f"Stopping kedr"):
        Kedr.stop()


@pytest.mark.os_dependent
@pytest.mark.parametrize("module", cas_module.CasModule)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_kedr_basic_io_raw(module, unload_modules, install_kedr):
    """
    title: Basic IO test with kedr started with memory leaks profile
    description: |
        Load CAS modules, start kedr against one of them, start cache and add core,
        run simple 4 minute random IO, stop cache and unload modules
    pass_criteria:
      - No memory leaks observed
    """
    with TestRun.step("Preparing cache device"):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_part = cache_device.partitions[0]

    with TestRun.step("Preparing core device"):
        core_device = TestRun.disks['core']
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        core_part = core_device.partitions[0]

    with TestRun.step("Unload CAS modules if needed"):
        if os_utils.is_kernel_module_loaded(module.value):
            cas_module.unload_all_cas_modules()

    with TestRun.step(f"Starting kedr against {module.value}"):
        Kedr.start(module.value)

    with TestRun.step(f"Loading CAS modules"):
        os_utils.load_kernel_module(cas_module.CasModule.cache.value)

    with TestRun.step("Starting cache"):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Adding core"):
        core = cache.add_core(core_dev=core_part)

    with TestRun.step(f"Running IO"):
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .run_time(timedelta(minutes=4))
              .time_based()
              .read_write(ReadWrite.randrw)
              .target(f"{core.path}")
              .direct()
         ).run()

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step(f"Unloading CAS modules"):
        cas_module.unload_all_cas_modules()

    with TestRun.step(f"Checking for memory leaks for {module.value}"):
        try:
            Kedr.check_for_mem_leaks(module.value)
        except Exception as e:
            TestRun.LOGGER.error(f"{e}")

    with TestRun.step(f"Stopping kedr"):
        Kedr.stop()


@pytest.mark.os_dependent
@pytest.mark.parametrize("module", cas_module.CasModule)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_kedr_basic_io_fs(module, unload_modules, install_kedr):
    """
    title: Basic IO test on core with ext4 filesystem with kedr started with memory leaks profile
    description: |
        Load CAS modules, start kedr against one of them, create filesystem on core, start cache
        and add core, run simple random IO, stop cache and unload modules
    pass_criteria:
      - No memory leaks observed
    """
    with TestRun.step("Preparing cache device"):
        cache_device = TestRun.disks['cache']
        cache_device.create_partitions([Size(500, Unit.MebiByte)])
        cache_part = cache_device.partitions[0]

    with TestRun.step("Preparing core device (creating partition, "
                      "filesystem and mounting core)"):
        core_device = TestRun.disks['core']
        core_device.create_partitions([Size(1, Unit.GibiByte)])
        core_part = core_device.partitions[0]
        core_part.create_filesystem(Filesystem.ext4)
        sync()

    with TestRun.step("Unload CAS modules if needed"):
        if os_utils.is_kernel_module_loaded(module.value):
            cas_module.unload_all_cas_modules()

    with TestRun.step(f"Starting kedr against {module.value}"):
        Kedr.start(module.value)

    with TestRun.step(f"Loading CAS modules"):
        os_utils.load_kernel_module(cas_module.CasModule.cache.value)

    with TestRun.step("Starting cache"):
        cache = casadm.start_cache(cache_part, force=True)

    with TestRun.step("Adding core"):
        core = cache.add_core(core_part)

    with TestRun.step("Mounting core"):
        core.mount(mountpoint)

    with TestRun.step(f"Running IO"):
        (Fio().create_command()
              .io_engine(IoEngine.libaio)
              .size(cache.size * 2)
              .read_write(ReadWrite.randrw)
              .target(f"{core.mount_point}/test_file")
         ).run()

    with TestRun.step("Unmounting core"):
        core.unmount()

    with TestRun.step("Stopping cache"):
        cache.stop()

    with TestRun.step(f"Unloading CAS modules"):
        cas_module.unload_all_cas_modules()

    with TestRun.step(f"Checking for memory leaks for {module.value}"):
        try:
            Kedr.check_for_mem_leaks(module.value)
        except Exception as e:
            TestRun.LOGGER.error(f"{e}")

    with TestRun.step(f"Stopping kedr"):
        Kedr.stop()
