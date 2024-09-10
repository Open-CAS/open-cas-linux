#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#


import os

from test_utils.git import get_repo_files
from api.cas.installer import (
    clean_opencas_repo,
    build_opencas,
    install_opencas,
    rsync_opencas_sources,
)
from core.test_run import TestRun
from test_tools.fs_utils import FilesPermissions, find_all_items


repo_files_perms_exceptions = {
    ".github/verify_header.sh": 755,
    "configure": 755,
    "doc/reqparse.py": 755,
    "test/smoke_test/basic/01": 755,
    "test/smoke_test/basic/02": 755,
    "test/smoke_test/basic/03": 755,
    "test/smoke_test/basic/04": 755,
    "test/smoke_test/basic/05": 755,
    "test/smoke_test/basic/06": 755,
    "test/smoke_test/basic/07": 755,
    "test/smoke_test/basic/08": 755,
    "test/smoke_test/basic/09": 755,
    "test/smoke_test/basic/10": 755,
    "test/smoke_test/basic/11": 755,
    "test/smoke_test/basic/12": 755,
    "test/smoke_test/basic/13": 755,
    "test/smoke_test/cache_suspend/01": 755,
    "test/smoke_test/cache_suspend/02": 755,
    "test/smoke_test/cache_suspend/03": 755,
    "test/smoke_test/eviction_policy/01": 755,
    "test/smoke_test/eviction_policy/02": 755,
    "test/smoke_test/eviction_policy/03": 755,
    "test/smoke_test/fio/01": 755,
    "test/smoke_test/incremental_load/01": 755,
    "test/smoke_test/incremental_load/02": 755,
    "test/smoke_test/init_script/01": 755,
    "test/smoke_test/init_script/02": 755,
    "test/smoke_test/init_script/03": 755,
    "test/smoke_test/io_class/01_wlth": 755,
    "test/smoke_test/io_class/02_wlth": 755,
    "test/smoke_test/metadata_corrupt/01": 755,
    "test/smoke_test/metadata_corrupt/02": 755,
    "test/smoke_test/promotion/01": 755,
    "test/smoke_test/recovery/01": 755,
    "test/smoke_test/recovery/02": 755,
    "test/smoke_test/run_tests": 755,
    "test/smoke_test/write_back/01": 755,
    "test/smoke_test/write_back/02": 755,
    "tools/cas_version_gen.sh": 755,
    "tools/pckgen.sh": 755,
    "tools/pckgen.d/deb/debian/rules": 755,
    "tools/version2sha.sh": 755,
    "utils/casctl": 755,
    "utils/open-cas-loader.py": 755,
    "utils/open-cas.shutdown": 755,
    "ocf/.github/verify_header.sh": 755,
    "ocf/tests/functional/utils/configure_random.py": 755,
    "ocf/tests/unit/framework/add_new_test_file.py": 755,
    "ocf/tests/unit/framework/prepare_sources_for_testing.py": 755,
    "ocf/tests/unit/framework/run_unit_tests.py": 755,
    "ocf/tests/unit/tests/add_new_test_file.py": 755,
}

build_files_perms_exceptions = {
    "casadm/casadm": 755,
}

installed_files_perms_exceptions = {
    "lib/opencas/casctl": 755,
    "lib/opencas/open-cas-loader.py": 755,
    "sbin/casadm": 755,
    "sbin/casctl": 755,
    "usr/lib/systemd/system-shutdown/open-cas.shutdown": 755,
}


def test_files_permissions():
    """
    title: Test for files and directories permissions
    description: |
      Check if all files and directories have proper permissions set.
      This icludes repo files and dirs, build artifacts and all
      installed items.
    pass_criteria:
      - all files and directories have proper permissions
    """

    with TestRun.step("Copy sources to working directory and cleanup"):
        rsync_opencas_sources()
        clean_opencas_repo()

    with TestRun.step("Check repo files and directories permissions"):
        files_list = get_repo_files(with_dirs=True, from_dut=True)
        repo_perms = FilesPermissions(files_list)

        perms_exceptions = {
            os.path.join(TestRun.usr.working_dir, file): perm
            for file, perm in repo_files_perms_exceptions.items()
        }
        repo_perms.add_exceptions(perms_exceptions)

        failed_perms = repo_perms.check()
        if failed_perms:
            message = ""
            for item in failed_perms:
                message += (
                    f"{item.file} current permissions: {item.current_perm}, "
                    f"expected: {item.expected_perm}\n"
                )
            TestRun.fail(f"Those files have wrong permissions:\n{message}")

    with TestRun.step("Check build files and directories permissions"):
        files_before_build = find_all_items(TestRun.usr.working_dir)
        build_opencas()
        files_after_build = find_all_items(TestRun.usr.working_dir)

        files_list = [file for file in files_after_build if file not in files_before_build]
        build_perms = FilesPermissions(files_list)

        perms_exceptions = {
            os.path.join(TestRun.usr.working_dir, file): perm
            for file, perm in build_files_perms_exceptions.items()
        }
        build_perms.add_exceptions(perms_exceptions)

        failed_perms = build_perms.check()
        if failed_perms:
            message = ""
            for item in failed_perms:
                message += (
                    f"{item.file} current permissions: {item.current_perm}, "
                    f"expected: {item.expected_perm}\n"
                )
            TestRun.fail(f"Those files have wrong permissions:\n{message}")

    with TestRun.step("Check installed files and directories permissions"):
        destdir = "install_destdir"
        install_opencas(destdir)

        files_list = find_all_items(os.path.join(TestRun.usr.working_dir, destdir))
        installed_perms = FilesPermissions(files_list)

        perms_exceptions = {
            os.path.join(TestRun.usr.working_dir, destdir, file): perm
            for file, perm in installed_files_perms_exceptions.items()
        }
        installed_perms.add_exceptions(perms_exceptions)

        failed_perms = installed_perms.check()
        if failed_perms:
            message = ""
            for item in failed_perms:
                message += (
                    f"{item.file} current permissions: {item.current_perm}, "
                    f"expected: {item.expected_perm}\n"
                )
            TestRun.fail(f"Those files have wrong permissions:\n{message}")
