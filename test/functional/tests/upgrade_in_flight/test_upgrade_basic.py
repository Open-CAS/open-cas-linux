#
# Copyright(c) 2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from git import Repo
import pytest
import sys
import time

from api.cas import casadm, version, git, installer, upgrade_in_flight
from api.cas.cache_config import CacheLineSize
from api.cas.casadm_parser import (
    get_caches,
    get_cas_cache_version,
    get_cas_disk_version,
    get_casadm_version,
    get_cores,
    get_statistics,
)
from api.cas.statistics import CacheStats, CoreStats
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_utils.output import CmdException
from upgrage_test_utils import *


def pytest_generate_tests(metafunc):
    if "cas_version_to_upgrade" in metafunc.fixturenames:
        test_path = os.path.realpath(__file__)
        repo = Repo(test_path, search_parent_directories=True)

        versions = version.get_upgradable_cas_versions(repo.commit())

        cas_versions = []
        metafunc.parametrize(
                "cas_version_to_upgrade",
                versions,
                indirect=True,
        )


@pytest.fixture
def cas_version_to_upgrade(request):
    return request.param


# TODO add clean installation mark when merged RPM tests will be merged
@pytest.mark.require_plugin("power_control")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize(
    "cache_line_size",
    [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_16KiB, CacheLineSize.LINE_64KiB],
)
def test_cas_upgrade_during_io(cache_line_size, cas_version_to_upgrade):
    """
    title: Upgrade CAS during IO
    description: |
      Verify CAS ability to upgrade in flight during IO.
    pass_criteria:
      - casadm and cas_cache version is updated
      - none of the CAS files (udev rules, casctl utils) are not changed
      - cas_disk version not changed until reboot
      - init config not changed
      - No system crash occured
      - CAS is working in the same configuration as before upgrade
      - Data integrity is not broken
    """
    with TestRun.step("Collect all versions and install older CAS"):
        #TODO Since cas will be uninstalled with test mark - remove this
        installer.uninstall_opencas()
        installer.set_up_opencas()

        original_commit = git.get_current_commit_hash(from_dut=True)
        original_casadm_version = get_casadm_version()
        original_cas_cache_version = get_cas_cache_version()
        installer.uninstall_opencas()
        installer.set_up_opencas(cas_version_to_upgrade)
        original_cas_disk_version = get_cas_disk_version()

    with TestRun.step("Prepare caches"):
        caches, configs = upgrade_prepare_caches(cache_line_size=cache_line_size)

    with TestRun.step("Store original stat config sections"):
        original_cache_config_sections = {}
        original_core_config_sections = {}

        for c in configs:
            original_cache_config_sections[c.cache_id] = CacheStats(
                get_statistics(cache_id=c.cache_id, filter=[casadm.StatsFilter.conf])
            ).config_stats

            original_core_config_sections[c.cache_id] = CoreStats(
                get_statistics(
                    cache_id=c.cache_id,
                    core_id=c.core_id,
                    filter=[casadm.StatsFilter.conf],
                )
            ).config_stats

    with TestRun.step("Gather all installed files paths"):
        files_to_update = upgrade_get_cas_files(cas_version_to_upgrade)

    with TestRun.step("Run fio to each instance"):
        [
            upgrade_get_fio_cmd(c.get_core_devices()[0]).run_in_background()
            for c in caches
        ]

    with TestRun.step("Sleep for 5 minutes"):
        time.sleep(300)

    with TestRun.step("Upgrade CAS in flight"):
        installer._clean_opencas_repo()
        git.checkout_cas_version(original_commit)
        upgrade_in_flight.upgrade_start()

    with TestRun.step("Check if correct number of caches is running after upgrade"):
        caches_after_upgrade = get_caches()
        running_caches_number = len(caches_after_upgrade)
        if len(caches_after_upgrade) != len(caches):
            TestRun.LOGGER.error(
                f"Expected {len(caches)} caches, got {len(caches_after_upgrade)}!"
            )

    with TestRun.step("Check if all instances have valid config"):
        for c in configs:
            upgrade_compare_cache_conf_section(
                original_cache_config_sections[c.cache_id]
            )
            upgrade_compare_core_conf_section(
                original_core_config_sections[c.cache_id], c.cache_id
            )
            upgrade_compare_ioclass_config(c.ioclass_config, c.cache_id)

            core_after_upgrade = get_cores(c.cache_id)
            if len(core_after_upgrade) != 1:
                TestRun.LOGGER.error(
                    f"cache {c.cache_id}: Expected 1 core, got {len(core_after_upgrade)}!"
                )

    with TestRun.step("Compare casadm and modules versions"):
        upgrade_verify_version_cmd(
            original_cas_disk_version,
            original_cas_cache_version,
            original_casadm_version,
        )

    with TestRun.step("Reboot DUT"):
        power_control = TestRun.plugin_manager.get_plugin("power_control")
        power_control.power_cycle()

    with TestRun.step(
        "Check if correct number of caches is running after upgrade and reboot"
    ):
        caches_after_upgrade = get_caches()
        running_caches_number = len(caches_after_upgrade)
        if len(caches_after_upgrade) != len(caches):
            TestRun.LOGGER.error(
                f"Expected {len(caches)} caches, got {len(caches_after_upgrade)}!"
            )

    with TestRun.step("Check if all instances have valid config after reboot"):
        for c in configs:
            upgrade_compare_cache_conf_section(
                original_cache_config_sections[c.cache_id]
            )
            upgrade_compare_core_conf_section(
                original_core_config_sections[c.cache_id], c.cache_id
            )
            upgrade_compare_ioclass_config(c.ioclass_config, c.cache_id)

            core_after_upgrade = get_cores(c.cache_id)
            if len(core_after_upgrade) != 1:
                TestRun.LOGGER.error(
                    f"cache {c.cache_id}: Expected 1 core, got {len(core_after_upgrade)}!"
                )

    with TestRun.step("Compare casadm and modules versions after reboot"):
        expected_cas_disk_version = original_cas_cache_version
        upgrade_verify_version_cmd(
            expected_cas_disk_version,
            original_cas_cache_version,
            original_casadm_version,
        )

    with TestRun.step("Compare files modification timestamps"):
        upgrade_check_files_updated(files_to_update)

    with TestRun.step("Cleanup - stop fio, stop cache, install original CAS version"):
        upgrade_teardown(original_commit)


@pytest.mark.remote_only
@pytest.mark.require_plugin("power_control")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cas_upgrade_negative():
    """
    title: Fail to upgrade from too old or current CAS version
    description: |
      Verify if upgrade script fails when not supported or newest CAS version is installed
    pass_criteria:
      - casadm, cas_cache and cas_disk version not changed
      - init config is not changed
      - none of the CAS files (udev rules, casctl utils) are not changed
      - CAS is working in the same configuration as before failed upgrade attempt
      - No system crash occured
    """
    with TestRun.step("Collect all versions and install non-upgradable CAS"):
        non_upgradable_cas_version = version.CasVersion("v19.9")
        original_commit = git.get_current_commit_hash(from_dut=True)
        installer.uninstall_opencas()
        installer.set_up_opencas(non_upgradable_cas_version)
        original_casadm_version = get_casadm_version()
        original_cas_cache_version = get_cas_cache_version()
        original_cas_disk_version = get_cas_disk_version()

    with TestRun.step("Prepare caches"):
        caches, configs = upgrade_prepare_caches(
            cache_line_size=CacheLineSize.LINE_4KiB
        )

    with TestRun.step("Store original stat config sections"):
        original_cache_config_sections = {}
        original_core_config_sections = {}

        for c in configs:
            original_cache_config_sections[c.cache_id] = CacheStats(
                get_statistics(cache_id=c.cache_id, filter=[casadm.StatsFilter.conf])
            ).config_stats

            original_core_config_sections[c.cache_id] = CoreStats(
                get_statistics(
                    cache_id=c.cache_id,
                    core_id=c.core_id,
                    filter=[casadm.StatsFilter.conf],
                )
            ).config_stats

    with TestRun.step("Gather all installed files paths"):
        files_to_update = upgrade_get_cas_files(non_upgradable_cas_version)

    with TestRun.step("Try to upgrade CAS"):
        installer._clean_opencas_repo()
        git.checkout_cas_version(original_commit)
        try:
            upgrade_in_flight.upgrade_start()
            upgrade_teardown(original_commit)
            TestRun.fail(
                f"upgrade CAS from {non_upgradable_cas_version} "
                f"to newest version should fail"
            )
        except CmdException:
            TestRun.LOGGER.info(
                f"upgrade CAS from {non_upgradable_cas_version} "
                f"to newest version failed"
            )

    with TestRun.step(
        "Check if correct number of caches is running after failed upgrade"
    ):
        caches_after_upgrade = get_caches()
        running_caches_number = len(caches_after_upgrade)
        if len(caches_after_upgrade) != len(caches):
            TestRun.LOGGER.error(
                f"Expected {len(caches)} caches, got {len(caches_after_upgrade)}!"
            )

    with TestRun.step("Check if all instances have valid config"):
        for c in configs:
            upgrade_compare_cache_conf_section(
                original_cache_config_sections[c.cache_id]
            )
            upgrade_compare_core_conf_section(
                original_core_config_sections[c.cache_id], c.cache_id
            )
            upgrade_compare_ioclass_config(c.ioclass_config, c.cache_id)

            core_after_upgrade = get_cores(c.cache_id)
            if len(core_after_upgrade) != 1:
                TestRun.LOGGER.error(
                    f"cache {c.cache_id}: Expected 1 core, got {len(core_after_upgrade)}!"
                )

    with TestRun.step("Compare casadm and modules versions"):
        upgrade_verify_version_cmd(
            original_cas_disk_version,
            original_cas_cache_version,
            original_casadm_version,
        )

    with TestRun.step("Compare files modification timestamps"):
        upgrade_check_files_not_updated(files_to_update)

    with TestRun.step("Cleanup - stop fio, stop cache, install original CAS version"):
        upgrade_teardown()
