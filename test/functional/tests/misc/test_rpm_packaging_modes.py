#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import re

import pytest

from api.cas.cas_packaging import Packages, get_packages_list
from api.cas.installer import clean_opencas_repo, rsync_opencas_sources
from core.test_run import TestRun
from test_tools.fs_tools import create_directory, remove


# Each package set is built once and kept on the DUT, to be reused by the other
# tests and by later runs: building the prebuilt variants compiles the modules,
# which is far too slow to repeat per test. Nothing deletes a set once it is
# there. Instead the cache is keyed on the packaging files it was built from,
# so a set is dropped when those change - which both bounds what accumulates
# and keeps a set built from other sources from being tested in place of one
# built from these.
packages_cache_root = "/var/tmp/cas_packaging_test"
packaging_inputs = ["version", "Makefile", "tools/pckgen.sh", "tools/pckgen.d/rpm/CAS_NAME.spec"]

main_package = "open-cas-linux"
dkms_modules_package = "open-cas-linux-modules"
prebuilt_modules_package_glob = "open-cas-linux-modules_k*"

# A version that is newer than whatever the sources are at. CAS majors follow
# the release month (03, 06, 09, 12), so 13 stays ahead of any release of the
# same main version - unlike a value picked to be one ahead of today's.
next_version = {"CAS_VERSION_MAJOR": "13"}

# The release being migrated from is a specific one - the last that shipped
# before the two packaging modes became mutually exclusive - so it is pinned
# rather than derived from the sources, which will move past it.
legacy_version = {
    "CAS_VERSION_MAIN": "26",
    "CAS_VERSION_MAJOR": "3",
    "CAS_VERSION_MINOR": "4",
}

# Variants are built from the same sources; only the spec conditional and the
# version differ. "legacy" additionally drops the Conflicts tag, to stand in
# for a package released before the two packaging modes were made exclusive.
variants = {
    "prebuilt": {"dkms": False, "version": None, "drop_conflicts": False},
    "dkms": {"dkms": True, "version": None, "drop_conflicts": False},
    "prebuilt_next": {"dkms": False, "version": next_version, "drop_conflicts": False},
    "dkms_next": {"dkms": True, "version": next_version, "drop_conflicts": False},
    "prebuilt_legacy": {"dkms": False, "version": legacy_version, "drop_conflicts": True},
}


def require_rpm_distro():
    distro_id_like = TestRun.executor.run_expect_success("grep -i ID_LIKE /etc/os-release").stdout

    if not re.search("rhel|fedora|suse|sles", distro_id_like):
        pytest.skip(f"{distro_id_like.strip()}: RPM packaging modes do not apply")


def require_dkms():
    if TestRun.executor.run("which dkms").exit_code != 0:
        pytest.skip("dkms is not available on this DUT")


def packages_cache_dir():
    """Cache location for the sources currently on the DUT."""
    inputs = " ".join(os.path.join(TestRun.usr.working_dir, f) for f in packaging_inputs)
    fingerprint = TestRun.executor.run_expect_success(
        f"cat {inputs} | md5sum | cut -c1-12"
    ).stdout.strip()

    # Sets built from anything else would silently be tested in place of these.
    TestRun.executor.run(
        f"find {packages_cache_root} -mindepth 1 -maxdepth 1 ! -name {fingerprint} "
        f"-exec rm -rf {{}} +"
    )

    return os.path.join(packages_cache_root, fingerprint)


def build_variant(name: str):
    """Build one package set, reusing it if a previous test already did."""
    packages_dir = os.path.join(packages_cache_dir(), name)

    cached = get_packages_list("rpm", packages_dir)
    if cached:
        return cached

    spec = os.path.join(
        TestRun.usr.working_dir, "tools", "pckgen.d", "rpm", "CAS_NAME.spec"
    )
    version_file = os.path.join(TestRun.usr.working_dir, "version")
    variant = variants[name]

    # the next variant builds from the same sources, so keep the originals
    for original in (version_file, spec):
        TestRun.executor.run_expect_success(f"cp -a {original} {original}.testbak")

    try:
        for field, value in (variant["version"] or {}).items():
            TestRun.executor.run_expect_success(
                f"sed -i 's/^{field}=.*/{field}={value}/' {version_file}"
            )
        if variant["drop_conflicts"]:
            # Without the tag actually being there to remove, this variant would
            # silently be an ordinary package and test nothing.
            if TestRun.executor.run(f"grep -q '^Conflicts:' {spec}").exit_code != 0:
                TestRun.fail(
                    "No Conflicts tag found to remove - a stand-in for a release made "
                    "before the packaging modes were exclusive cannot be built"
                )
            TestRun.executor.run_expect_success(f"sed -i '/^Conflicts:/d' {spec}")

        create_directory(packages_dir, parents=True)
        cas_packages = Packages([], packages_dir)
        cas_packages.create(
            TestRun.usr.working_dir, packages_dir=packages_dir, dkms=variant["dkms"]
        )
        return cas_packages.packages
    finally:
        for original in (version_file, spec):
            TestRun.executor.run(f"mv -f {original}.testbak {original}")


def source_version_field(field: str):
    version_file = os.path.join(TestRun.usr.working_dir, "version")
    return TestRun.executor.run_expect_success(
        f"grep -E '^{field}=' {version_file} | cut -d= -f2"
    ).stdout.strip()


def variant_version(name: str):
    """The version prefix a variant's packages carry, e.g. '26.13'."""
    overrides = variants[name]["version"] or {}
    main = overrides.get("CAS_VERSION_MAIN") or source_version_field("CAS_VERSION_MAIN")
    major = overrides.get("CAS_VERSION_MAJOR") or source_version_field("CAS_VERSION_MAJOR")

    return f"{int(main)}.{int(major):02d}"


def prepare_sources():
    rsync_opencas_sources()
    clean_opencas_repo()


def packages_of(variant: str, kind: str = "all"):
    """Paths of a variant's packages: the tools, the modules, or both."""
    packages = [p for p in build_variant(variant) if "debug" not in os.path.basename(p)]

    if kind == "modules":
        return [p for p in packages if "-modules" in os.path.basename(p)]
    if kind == "main":
        return [p for p in packages if "-modules" not in os.path.basename(p)]
    return packages


# The prebuilt modules package is named after the kernel it was built for, so
# its name starts with the DKMS package's name - anchor on what follows to tell
# the three packages apart instead of matching substrings.
tools_package_re = re.compile(rf"^{main_package}-\d")
dkms_modules_re = re.compile(rf"^{dkms_modules_package}-\d")
prebuilt_modules_re = re.compile(rf"^{dkms_modules_package}_k")


def installed_cas_packages():
    output = TestRun.executor.run(f"rpm --query --all | grep '^{main_package}'")
    return sorted(line.strip() for line in output.stdout.splitlines() if line.strip())


def tools_installed():
    return any(tools_package_re.match(pkg) for pkg in installed_cas_packages())


def modules_installed(mode: str):
    pattern = dkms_modules_re if mode == "dkms" else prebuilt_modules_re
    return any(pattern.match(pkg) for pkg in installed_cas_packages())


def dnf(command: str, packages: list, allowerasing: bool = False):
    """Run a dnf transaction without raising - several tests expect refusal."""
    opts = "--allowerasing " if allowerasing else ""
    return TestRun.executor.run(f"dnf -y {command} {opts}{' '.join(packages)}")


def wait_for_orphan_removal():
    """The kmod->dkms cleanup is a detached worker that waits for dnf to exit."""
    TestRun.executor.run(
        f"for i in $(seq 1 30); do "
        f"rpm --query --all '{prebuilt_modules_package_glob}' | grep -q . || break; "
        f"sleep 3; done"
    )


def dkms_status():
    return TestRun.executor.run("dkms status 2>/dev/null").stdout.strip()


def modules_load():
    """Reload the CAS modules from disk, returning True when that works."""
    TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
    return TestRun.executor.run("modprobe cas_cache").exit_code == 0


def installed_module_version():
    output = TestRun.executor.run("casadm -V")
    match = re.search(r"CAS Cache Kernel Module\s*\|\s*(\S+)", output.stdout)
    return match.group(1) if match else None


def initramfs_rebuild_works():
    return TestRun.executor.run("dracut --regenerate-all --force").exit_code == 0


def stale_module_links():
    output = TestRun.executor.run(
        "find /lib/modules -path '*weak-updates*' -name 'cas_*' -xtype l"
    )
    return [line.strip() for line in output.stdout.splitlines() if line.strip()]


def service_links():
    output = TestRun.executor.run(
        "find /etc/systemd/system -name 'open-cas*.service' 2>/dev/null"
    )
    return [line.strip() for line in output.stdout.splitlines() if line.strip()]


def local_fs_target_starts():
    """open-cas.service is RequiredBy local-fs.target, so a dangling link breaks it."""
    return TestRun.executor.run("systemctl start local-fs.target").exit_code == 0


def purge_cas():
    """Leave no CAS packages, modules, DKMS registration or stale links behind."""
    TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
    TestRun.executor.run(
        f"rpm --query --all | grep '^{main_package}' | "
        f"xargs --no-run-if-empty rpm --erase --nodeps --noscripts"
    )
    # --noscripts skips %preun, which would disable the services; a dangling
    # open-cas.service link fails local-fs.target and leaves / read-only on boot
    TestRun.executor.run(
        "find /etc/systemd/system -name 'open-cas*.service' -delete; "
        "systemctl daemon-reload"
    )
    TestRun.executor.run(
        "dkms status 2>/dev/null | cut -d, -f1 | tr -d ' ' | while IFS=/ read -r m v; do "
        "[ -n \"$m\" ] && dkms remove -m \"$m\" -v \"$v\" --all; done"
    )
    remove(f"/var/lib/dkms/{dkms_modules_package}", recursive=True, force=True, ignore_errors=True)
    TestRun.executor.run(f"rm -rf /usr/src/{dkms_modules_package}-*")
    TestRun.executor.run(
        r"find /lib/modules \( -name 'cas_*.ko*' -o -path '*block/opencas*' \) -delete"
    )
    TestRun.executor.run(
        r"find /lib/modules -depth -type d \( -path '*weak-updates/block*' "
        r"-o -path '*extra/block*' \) -empty -delete"
    )
    TestRun.executor.run(
        "for k in $(ls /lib/modules); do "
        "[ -e /lib/modules/$k/modules.dep ] && depmod -a $k; done"
    )


def setup_packaging_test(dkms_needed: bool = True):
    require_rpm_distro()
    if dkms_needed:
        require_dkms()
    prepare_sources()
    purge_cas()


@pytest.fixture(autouse=True)
def leave_no_installation_behind():
    """
    Every test installs packages and must not hand them to the next one: the
    order tests run in is not fixed and they may not even run on the same DUT,
    so each cleans up after itself rather than relying on a test that does.
    """
    yield

    if TestRun.executor.run("which rpm").exit_code == 0:
        purge_cas()


@pytest.mark.os_dependent
def test_rpm_packaging_modes_metadata():
    """
    title: RPM packaging modes produce the expected packages and dependencies.
    description: |
      Check that the prebuilt and DKMS packaging modes each produce the kind of
      modules package they are meant to, that the two are declared mutually
      exclusive, and that both satisfy the same dependency of the tools package.
    pass_criteria:
      - prebuilt mode produces a per-kernel, architecture specific modules package
      - DKMS mode produces a single noarch modules package
      - the prebuilt modules package conflicts with the DKMS one
      - both modules packages provide the symbol the tools package requires
    """

    with TestRun.step("Prepare sources"):
        require_rpm_distro()
        prepare_sources()

    with TestRun.step("Build both packaging modes"):
        prebuilt = packages_of("prebuilt", "modules")
        dkms = packages_of("dkms", "modules")

    with TestRun.step("Check the modules packages are of the expected kind"):
        prebuilt_name = os.path.basename(prebuilt[0])
        dkms_name = os.path.basename(dkms[0])

        if "modules_k" not in prebuilt_name or prebuilt_name.endswith("noarch.rpm"):
            TestRun.fail(
                f"Prebuilt mode should produce a per-kernel arch package, got {prebuilt_name}"
            )
        if not dkms_name.endswith("noarch.rpm"):
            TestRun.fail(f"DKMS mode should produce a noarch package, got {dkms_name}")

    with TestRun.step("Check the two modules packages exclude each other"):
        conflicts = TestRun.executor.run(f"rpm --query --package --conflicts {prebuilt[0]}").stdout

        if dkms_modules_package not in conflicts:
            TestRun.fail(
                f"Prebuilt modules package should conflict with '{dkms_modules_package}', "
                f"its conflicts are: {conflicts.strip() or 'none'}"
            )

    with TestRun.step("Check both satisfy the same dependency of the tools package"):
        required = TestRun.executor.run(
            f"rpm --query --package --requires {packages_of('dkms', 'main')[0]} | grep modules"
        ).stdout.strip()

        for modules_package in (prebuilt[0], dkms[0]):
            provides = TestRun.executor.run(
                f"rpm --query --package --provides {modules_package}"
            ).stdout
            if required not in provides:
                TestRun.fail(
                    f"{os.path.basename(modules_package)} does not provide '{required}', "
                    f"so switching modes would take the tools package with it"
                )


@pytest.mark.os_dependent
@pytest.mark.parametrize("mode", ["prebuilt", "dkms"])
def test_rpm_packaging_install_uninstall(mode):
    """
    title: Install and uninstall Open CAS in either RPM packaging mode.
    description: |
      Install the tools and modules packages of one packaging mode, check the
      modules can be loaded, then uninstall and check nothing is left behind.
    pass_criteria:
      - packages install and the CAS modules load
      - uninstalling removes every package, module and DKMS registration
      - no stale module links remain and the initramfs can still be rebuilt
      - no service links remain and local-fs.target still starts
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test(dkms_needed=(mode == "dkms"))

    with TestRun.step(f"Install the {mode} packages"):
        output = dnf("install", packages_of(mode))
        if output.exit_code != 0:
            TestRun.fail(f"Installing the {mode} packages failed:\n{output.stdout}")

    with TestRun.step("Check the modules load"):
        if not modules_load():
            TestRun.fail(f"CAS modules could not be loaded with the {mode} packages")
        TestRun.LOGGER.info(f"Loaded module version: {installed_module_version()}")

        if mode == "dkms" and "installed" not in dkms_status():
            TestRun.fail(f"DKMS reports no installed modules:\n{dkms_status()}")

    with TestRun.step("Uninstall and check nothing is left behind"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        output = dnf("remove", [main_package] + [
            os.path.basename(p).rsplit("-", 2)[0] for p in packages_of(mode, "modules")
        ])
        if output.exit_code != 0:
            TestRun.fail(f"Uninstalling the {mode} packages failed:\n{output.stdout}")

        if installed_cas_packages():
            TestRun.fail(f"Packages left installed: {installed_cas_packages()}")

        leftover_modules = TestRun.executor.run(
            "find /lib/modules -name 'cas_*.ko*'"
        ).stdout.strip()
        if leftover_modules:
            TestRun.fail(f"CAS modules left on disk after uninstall:\n{leftover_modules}")

        if stale_module_links():
            TestRun.fail(f"Stale module links left behind: {stale_module_links()}")

        if service_links():
            TestRun.fail(f"Service links left behind: {service_links()}")

        if not local_fs_target_starts():
            TestRun.fail("local-fs.target does not start after uninstall")

        if not initramfs_rebuild_works():
            TestRun.fail("Initramfs could not be rebuilt after uninstall")


@pytest.mark.os_dependent
@pytest.mark.parametrize("installed_mode,other_mode", [("prebuilt", "dkms"), ("dkms", "prebuilt")])
def test_rpm_packaging_mode_switch_is_refused(installed_mode, other_mode):
    """
    title: Installing the other packaging mode over an existing one is refused.
    description: |
      The two modules packages both provide modules for the same kernel, so they
      are declared mutually exclusive. Installing one while the other is present
      has to be refused rather than silently leaving both installed.
    pass_criteria:
      - the transaction is refused and reports the conflict
      - the originally installed packages are untouched and still work
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step(f"Install the {installed_mode} packages"):
        if dnf("install", packages_of(installed_mode)).exit_code != 0:
            TestRun.fail(f"Could not install the {installed_mode} packages")
        installed_before = installed_cas_packages()

    with TestRun.step(f"Try to install the {other_mode} modules package over it"):
        output = dnf("install", packages_of(other_mode, "modules"))

        if output.exit_code == 0:
            TestRun.fail(
                f"Installing the {other_mode} modules package over the {installed_mode} "
                f"one was allowed, leaving: {installed_cas_packages()}"
            )
        if "conflict" not in (output.stdout + output.stderr).lower():
            TestRun.fail(f"Refused, but not because of the conflict:\n{output.stdout}")

    with TestRun.step("Check the installed packages were left untouched"):
        if installed_cas_packages() != installed_before:
            TestRun.fail(
                f"Refused transaction still changed what is installed:\n"
                f"before: {installed_before}\nafter:  {installed_cas_packages()}"
            )
        if not modules_load():
            TestRun.fail("CAS modules no longer load after the refused transaction")


@pytest.mark.os_dependent
@pytest.mark.parametrize("from_mode,to_mode", [("prebuilt", "dkms"), ("dkms", "prebuilt")])
def test_rpm_packaging_mode_switch_when_requested(from_mode, to_mode):
    """
    title: Switching packaging mode on request replaces one with the other.
    description: |
      Switching modes is supported, it just has to be asked for explicitly.
      Check that doing so replaces the modules package, keeps the tools package
      installed, and leaves working modules behind.
    pass_criteria:
      - the switch succeeds and only the requested modules package remains
      - the tools package is not removed along with the old modules package
      - the CAS modules load afterwards
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step(f"Install the {from_mode} packages"):
        if dnf("install", packages_of(from_mode)).exit_code != 0:
            TestRun.fail(f"Could not install the {from_mode} packages")

    with TestRun.step(f"Switch to the {to_mode} packages"):
        output = dnf("install", packages_of(to_mode, "modules"), allowerasing=True)
        if output.exit_code != 0:
            TestRun.fail(f"Requested switch to {to_mode} failed:\n{output.stdout}")

    with TestRun.step("Check the outcome"):
        if not tools_installed():
            TestRun.fail(
                f"Switching to {to_mode} removed the tools package as well, leaving: "
                f"{installed_cas_packages()}"
            )

        if not modules_installed(to_mode):
            TestRun.fail(
                f"{to_mode} modules package is not installed: {installed_cas_packages()}"
            )
        if modules_installed(from_mode):
            TestRun.fail(
                f"{from_mode} modules package was left installed: {installed_cas_packages()}"
            )

        if not modules_load():
            TestRun.fail(f"CAS modules do not load after switching to {to_mode}")


@pytest.mark.os_dependent
@pytest.mark.parametrize("mode", ["prebuilt", "dkms"])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_rpm_packaging_version_change_same_mode(mode, direction):
    """
    title: Upgrade and downgrade Open CAS within one packaging mode.
    description: |
      Move between two versions of the same packaging mode in both directions
      and check the resulting installation is the expected version and works.
    pass_criteria:
      - the transaction succeeds and the expected version ends up installed
      - the CAS modules of that version load afterwards
      - the initramfs can still be rebuilt
    """

    older, newer = mode, f"{mode}_next"
    start, target = (older, newer) if direction == "upgrade" else (newer, older)

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test(dkms_needed=(mode == "dkms"))

    with TestRun.step(f"Install the starting packages ({start})"):
        if dnf("install", packages_of(start)).exit_code != 0:
            TestRun.fail(f"Could not install the {start} packages")

    with TestRun.step(f"{direction.capitalize()} to {target}"):
        output = dnf(direction, packages_of(target))
        if output.exit_code != 0:
            TestRun.fail(f"{direction.capitalize()} to {target} failed:\n{output.stdout}")

    with TestRun.step("Check the resulting installation"):
        expected_version = variant_version(target)
        installed = " ".join(installed_cas_packages())
        if expected_version not in installed:
            TestRun.fail(f"Expected {expected_version} to be installed, got: {installed}")

        if not modules_load():
            TestRun.fail(f"CAS modules do not load after {direction} to {target}")

        loaded_version = installed_module_version()
        if loaded_version and expected_version not in loaded_version:
            TestRun.fail(
                f"Loaded module is {loaded_version}, expected {expected_version} "
                f"after {direction}"
            )

        if not initramfs_rebuild_works():
            TestRun.fail(f"Initramfs could not be rebuilt after {direction} to {target}")


@pytest.mark.os_dependent
@pytest.mark.parametrize("from_mode,to_mode", [("prebuilt", "dkms_next"), ("dkms", "prebuilt_next")])
def test_rpm_packaging_cross_mode_version_change_is_refused(from_mode, to_mode):
    """
    title: Changing packaging mode and version at once is refused.
    description: |
      A newer release of the other packaging mode must not be able to replace
      the installed one as an ordinary upgrade - switching modes stays an
      explicit decision even when a version change comes with it.
    pass_criteria:
      - the transaction is refused and reports the conflict
      - the originally installed packages are untouched and still work
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step(f"Install the {from_mode} packages"):
        if dnf("install", packages_of(from_mode)).exit_code != 0:
            TestRun.fail(f"Could not install the {from_mode} packages")
        installed_before = installed_cas_packages()

    with TestRun.step(f"Try to upgrade into the other mode ({to_mode})"):
        output = dnf("install", packages_of(to_mode))

        if output.exit_code == 0:
            TestRun.fail(
                f"Upgrading from {from_mode} into {to_mode} was allowed, "
                f"leaving: {installed_cas_packages()}"
            )
        if "conflict" not in (output.stdout + output.stderr).lower():
            TestRun.fail(f"Refused, but not because of the conflict:\n{output.stdout}")

    with TestRun.step("Check the installed packages were left untouched"):
        if installed_cas_packages() != installed_before:
            TestRun.fail(
                f"Refused transaction still changed what is installed:\n"
                f"before: {installed_before}\nafter:  {installed_cas_packages()}"
            )
        if not modules_load():
            TestRun.fail("CAS modules no longer load after the refused transaction")


@pytest.mark.os_dependent
def test_rpm_packaging_migration_from_released_prebuilt():
    """
    title: Migrate an installation made before the packaging modes existed.
    description: |
      Packages released before the two modes were made mutually exclusive carry
      no conflict, so installing the DKMS package over one of them is allowed
      and has to clean the old per-kernel package up afterwards. The old package
      is stood in for by one built with the conflict removed.
    pass_criteria:
      - the DKMS package installs over the old prebuilt one
      - the old per-kernel modules package is removed afterwards
      - no stale module links remain, modules load and the initramfs rebuilds
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step("Install a prebuilt package with no conflict declared"):
        if dnf("install", packages_of("prebuilt_legacy")).exit_code != 0:
            TestRun.fail("Could not install the stand-in for a released prebuilt package")

        if not tools_installed():
            TestRun.fail("The stand-in package did not install")

    with TestRun.step("Install the DKMS packages over it"):
        output = dnf("install", packages_of("dkms"))
        if output.exit_code != 0:
            TestRun.fail(f"Migration to DKMS failed:\n{output.stdout}")

    with TestRun.step("Check the old per-kernel package is cleaned up"):
        wait_for_orphan_removal()

        leftover = TestRun.executor.run(
            f"rpm --query --all '{prebuilt_modules_package_glob}'"
        ).stdout.strip()
        if leftover:
            TestRun.fail(f"Old per-kernel modules package was not removed: {leftover}")

        if not modules_installed("dkms"):
            TestRun.fail(f"DKMS modules package is not installed: {installed_cas_packages()}")

    with TestRun.step("Check the result is a working DKMS installation"):
        if "installed" not in dkms_status():
            TestRun.fail(f"DKMS reports no installed modules:\n{dkms_status()}")

        if stale_module_links():
            TestRun.fail(f"Stale module links left after migration: {stale_module_links()}")

        if not modules_load():
            TestRun.fail("CAS modules do not load after migration")

        if not initramfs_rebuild_works():
            TestRun.fail("Initramfs could not be rebuilt after migration")


@pytest.mark.os_dependent
def test_rpm_packaging_migration_keeps_modules_when_dkms_build_fails():
    """
    title: A failed DKMS build does not take the existing modules away.
    description: |
      The cleanup of the old per-kernel package runs after the transaction, so
      it must not act on a DKMS build that produced nothing - otherwise it would
      remove the only modules the running kernel has. Checked by registering the
      DKMS sources without ever building them.
    pass_criteria:
      - the old per-kernel modules package is still installed
      - its modules are still on disk and still load
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step("Install a prebuilt package with no conflict declared"):
        if dnf("install", packages_of("prebuilt_legacy")).exit_code != 0:
            TestRun.fail("Could not install the stand-in for a released prebuilt package")

    with TestRun.step("Put the DKMS sources in place without building them"):
        dkms_package = packages_of("dkms", "modules")[0]
        TestRun.executor.run_expect_success(
            f"rpm --install --noscripts --nodeps {dkms_package}"
        )

        if "installed" in dkms_status():
            TestRun.fail(f"DKMS should have nothing installed here:\n{dkms_status()}")

    with TestRun.step("Run the cleanup the way the package would"):
        version = TestRun.executor.run_expect_success(
            f"rpm --query --queryformat '%{{VERSION}}' {dkms_modules_package}"
        ).stdout.strip()

        removed = TestRun.executor.run(
            f'dkms status -m {dkms_modules_package} -v {version} -k "$(uname -r)" '
            f'2>/dev/null | grep -q ": installed"'
        ).exit_code == 0

        if removed:
            TestRun.fail(
                "The cleanup would have removed the prebuilt package even though "
                "DKMS has no modules installed"
            )

    with TestRun.step("Check the existing modules are still there and usable"):
        leftover = TestRun.executor.run(
            f"rpm --query --all '{prebuilt_modules_package_glob}'"
        ).stdout.strip()
        if not leftover:
            TestRun.fail("The prebuilt modules package was removed despite the failed build")

        if not modules_load():
            TestRun.fail("CAS modules no longer load")
