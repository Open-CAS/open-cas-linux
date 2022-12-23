#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import wget
import os
from enum import Enum

from core.test_run import TestRun
from test_tools import fs_utils
from test_utils.os_utils import DEBUGFS_MOUNT_POINT


KEDR_0_6_URL = "https://github.com/euspectre/kedr/archive/v0.6.tar.gz"
BUILD_DIR = "build"
LEAKS_LOGS_PATH = f"{DEBUGFS_MOUNT_POINT}/kedr_leak_check"
KMALLOC_FAULT_SIMULATION_PATH = "/sys/kernel/debug/kedr_fault_simulation"


class KedrProfile(Enum):
    MEM_LEAK_CHECK = "leak_check.conf"
    FAULT_SIM = "fsim.conf"


class Kedr:
    @staticmethod
    def is_installed():
        return "KEDR version" in TestRun.executor.run("kedr --version").stdout.strip()

    @classmethod
    def install(cls):
        if cls.is_installed():
            TestRun.LOGGER.info("Kedr is already installed!")
            return

        # TODO check if cmake is installed before
        # TODO consider using os_utils.download_file()
        kedr_archive = wget.download(KEDR_0_6_URL)

        TestRun.executor.rsync_to(
            f"\"{kedr_archive}\"",
            f"{TestRun.config['working_dir']}")

        kedr_dir = TestRun.executor.run_expect_success(
            f"cd {TestRun.config['working_dir']} && "
            f"tar -ztf \"{kedr_archive}\" | sed -e 's@/.*@@' | uniq"
        ).stdout

        TestRun.executor.run_expect_success(
            f"cd {TestRun.config['working_dir']} && "
            f"tar -xf \"{kedr_archive}\" && "
            f"cd {kedr_dir} && "
            f"mkdir -p {BUILD_DIR} && "
            f"cd {BUILD_DIR} && "
            f"cmake ../sources/ && "
            f"make && "
            f"make install"
        )

        os.remove(kedr_archive)
        TestRun.LOGGER.info("Kedr installed succesfully")

    @classmethod
    def is_loaded(cls):
        if not cls.is_installed():
            raise Exception("Kedr is not installed!")

        if "KEDR status: loaded" in TestRun.executor.run_expect_success("kedr status").stdout:
            return True
        else:
            return False

    @classmethod
    def start(cls, module, profile: KedrProfile = KedrProfile.MEM_LEAK_CHECK):
        if not cls.is_installed():
            raise Exception("Kedr is not installed!")

        TestRun.LOGGER.info(f"Starting kedr with {profile} profile")
        start_cmd = f"kedr start {module} -f {profile.value}"
        TestRun.executor.run_expect_success(start_cmd)

    # TODO extend to scenarios other than kmalloc
    def setup_fault_injections(condition: str = "1"):
        TestRun.executor.run_expect_success(
            f'echo "kmalloc" > {KMALLOC_FAULT_SIMULATION_PATH}/points/kmalloc/current_indicator')
        TestRun.executor.run_expect_success(
            f'echo "{condition}" > {KMALLOC_FAULT_SIMULATION_PATH}/points/kmalloc/expression')

    @classmethod
    def fsim_show_last_fault(cls):
        if not cls.is_installed():
            raise Exception("Kedr is not installed!")

        if not cls.is_loaded():
            raise Exception("Kedr is not loaded!")

        return fs_utils.read_file(f"{KMALLOC_FAULT_SIMULATION_PATH}/last_fault")

    @classmethod
    def stop(cls):
        if not cls.is_installed():
            raise Exception("Kedr is not installed!")

        TestRun.executor.run_expect_success("kedr stop")

    @classmethod
    def check_for_mem_leaks(cls, module):
        if not cls.is_installed():
            raise Exception("Kedr is not installed!")

        if not cls.is_loaded():
            raise Exception("Kedr is not loaded!")

        if fs_utils.check_if_directory_exists(f"{LEAKS_LOGS_PATH}/{module}"):
            logs_path = f"{LEAKS_LOGS_PATH}/{module}"
        elif fs_utils.check_if_directory_exists(f"{DEBUGFS_MOUNT_POINT}"):
            logs_path = f"{LEAKS_LOGS_PATH}"
        else:
            raise Exception("Couldn't find kedr logs dir!")

        leaks = fs_utils.read_file(f"{logs_path}/possible_leaks")
        frees = fs_utils.read_file(f"{logs_path}/unallocated_frees")
        summary = fs_utils.read_file(f"{logs_path}/info")
        if leaks or frees:
            raise Exception("Memory leaks found!\n"
                            f"Kedr summary: {summary}\n"
                            f"Possible memory leaks: {leaks}\n"
                            f"Unallocated frees: {frees}\n")
