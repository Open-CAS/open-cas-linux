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


# DEB packages always ship the kernel modules as DKMS sources, so unlike RPM
# there is a single packaging mode and building a set does not compile the
# modules - it takes seconds, so each test builds what it needs from scratch.
# Within one test a set is built once and reused.
packages_root = "/var/tmp/cas_deb_packaging_test"
built_sets = {}

main_package = "open-cas-linux"
modules_package = "open-cas-linux-dkms"
# DKMS registers the sources under the project name, not the package name
dkms_module = main_package
# What the DKMS package was called, and registered in DKMS as, up to 26.03
legacy_modules_package = "open-cas-linux-modules"
cas_services = ["open-cas.service", "open-cas-shutdown.service"]

# A version that is newer than whatever the sources are at. CAS majors follow
# the release month (03, 06, 09, 12), so 13 stays ahead of any release of the
# same main version - unlike a value picked to be one ahead of today's.
next_version = {"CAS_VERSION_MAJOR": "13"}

variants = {
    "current": {"version": None},
    "next": {"version": next_version},
}


def require_deb_distro():
    distro_id_like = TestRun.executor.run_expect_success("grep -i ID_LIKE /etc/os-release").stdout

    if not re.search("debian", distro_id_like):
        pytest.skip(f"{distro_id_like.strip()}: DEB packaging does not apply")


def require_dkms():
    if TestRun.executor.run("which dkms").exit_code != 0:
        pytest.skip("dkms is not available on this DUT")


def prepare_sources():
    rsync_opencas_sources()
    clean_opencas_repo()


def build_variant(name: str, debug: bool = False):
    """Build one package set from the sources on the DUT."""
    if (name, debug) in built_sets:
        return built_sets[(name, debug)]

    packages_dir = os.path.join(packages_root, f"{name}{'_debug' if debug else ''}")
    remove(packages_dir, recursive=True, force=True, ignore_errors=True)

    version_file = os.path.join(TestRun.usr.working_dir, "version")
    overrides = variants[name]["version"] or {}

    # every variant builds from the same sources, so keep the original
    TestRun.executor.run_expect_success(f"cp -a {version_file} {version_file}.testbak")

    try:
        for field, value in overrides.items():
            TestRun.executor.run_expect_success(
                f"sed -i 's/^{field}=.*/{field}={value}/' {version_file}"
            )

        create_directory(packages_dir, parents=True)
        cas_packages = Packages([], packages_dir)
        cas_packages.create(TestRun.usr.working_dir, packages_dir=packages_dir, debug=debug)
        built_sets[(name, debug)] = cas_packages.packages
        return cas_packages.packages
    finally:
        TestRun.executor.run(f"mv -f {version_file}.testbak {version_file}")


def package_name(package_path: str):
    return os.path.basename(package_path).split("_")[0]


def package_field(package_path: str, field: str):
    return TestRun.executor.run_expect_success(
        f"dpkg-deb --field {package_path} {field}"
    ).stdout.strip()


def package_files(package_path: str):
    output = TestRun.executor.run_expect_success(f"dpkg-deb --fsys-tarfile {package_path} | tar -t")
    return [line.strip().lstrip(".") for line in output.stdout.splitlines() if line.strip()]


def split_packages(packages: list):
    """Map a set's binary packages by name, checking it is the expected set."""
    by_name = {package_name(p): p for p in packages if p.endswith(".deb")}

    if sorted(by_name) != sorted([main_package, modules_package]):
        TestRun.fail(
            f"Expected packages {main_package} and {modules_package}, got: "
            f"{[os.path.basename(p) for p in packages]}"
        )
    return by_name


def packages_of(variant: str):
    return list(split_packages(build_variant(variant)).values())


def upstream_version(package_path: str):
    """The version without the Debian revision - the one DKMS and CAS report."""
    return package_field(package_path, "Version").rsplit("-", 1)[0]


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


def apt_get(command: str, packages: list, options: str = ""):
    """Run an apt-get transaction without raising - some tests expect refusal."""
    return TestRun.executor.run(
        f"DEBIAN_FRONTEND=noninteractive apt-get --yes {options} {command} {' '.join(packages)}"
    )


def cas_packages_state():
    """Package name -> (dpkg status abbreviation, version) of every CAS package dpkg knows."""
    output = TestRun.executor.run(
        f"dpkg-query --show --showformat='${{db:Status-Abbrev}} ${{Package}} ${{Version}}\\n' "
        f"'{main_package}*'"
    )
    state = {}
    for line in output.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3:
            state[fields[1]] = (fields[0], fields[2])
    return state


def installed_cas_packages():
    return sorted(
        f"{name} {version}"
        for name, (status, version) in cas_packages_state().items()
        if status == "ii"
    )


def kernels_with_headers():
    """Kernels DKMS is expected to build for: installed, with headers to build against."""
    output = TestRun.executor.run_expect_success(
        "for k in $(ls /lib/modules); do "
        "[ -e /lib/modules/$k/build ] && [ -e /boot/vmlinuz-$k ] && echo $k; done; true"
    )
    return sorted(line.strip() for line in output.stdout.splitlines() if line.strip())


def running_kernel():
    return TestRun.executor.run_expect_success("uname -r").stdout.strip()


def dkms_status():
    return TestRun.executor.run("dkms status 2>/dev/null").stdout.strip()


def dkms_installed_kernels(version: str):
    """Kernels DKMS reports the given version of the CAS modules installed for."""
    output = TestRun.executor.run(f"dkms status -m {dkms_module} -v {version} 2>/dev/null")
    return sorted(
        match.group(1)
        for match in re.finditer(r"^[^,]+,\s*([^,]+),[^:]*:\s*installed", output.stdout, re.M)
    )


def module_version_on_disk(kernel: str):
    output = TestRun.executor.run(f"modinfo -k {kernel} -F version cas_cache")
    return output.stdout.strip() if output.exit_code == 0 else None


def modules_load():
    """Reload the CAS modules from disk, returning True when that works."""
    TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
    return TestRun.executor.run("modprobe cas_cache").exit_code == 0


def installed_module_version():
    output = TestRun.executor.run("casadm -V")
    match = re.search(r"CAS Cache Kernel Module\s*\|\s*(\S+)", output.stdout)
    return match.group(1) if match else None


def services_enabled():
    return all(
        TestRun.executor.run(f"systemctl is-enabled --quiet {service}").exit_code == 0
        for service in cas_services
    )


def service_links():
    output = TestRun.executor.run(
        "find /etc/systemd/system -name 'open-cas*.service' 2>/dev/null"
    )
    return [line.strip() for line in output.stdout.splitlines() if line.strip()]


def local_fs_target_starts():
    """open-cas.service is RequiredBy local-fs.target, so a dangling link breaks it."""
    return TestRun.executor.run("systemctl start local-fs.target").exit_code == 0


def check_modules_for_all_kernels(version: str):
    """DKMS must have built and installed the given version for every kernel."""
    expected = kernels_with_headers()
    installed = dkms_installed_kernels(version)

    missing = [kernel for kernel in expected if kernel not in installed]
    if missing:
        TestRun.fail(
            f"DKMS did not install {version} for kernels {missing}:\n{dkms_status()}"
        )

    for kernel in expected:
        on_disk = module_version_on_disk(kernel)
        if on_disk != version:
            TestRun.fail(f"cas_cache for {kernel} is version {on_disk}, expected {version}")

    other_versions = [
        line for line in dkms_status().splitlines()
        if line.startswith(f"{dkms_module}/") and f"/{version}," not in line
    ]
    if other_versions:
        TestRun.fail(f"Other CAS versions are still registered in DKMS:\n{other_versions}")

    stale_sources = TestRun.executor.run(
        f"ls -d /usr/src/{dkms_module}-* | grep -v -- '-{version}$'"
    ).stdout.strip()
    if stale_sources:
        TestRun.fail(f"Sources of other CAS versions are left behind:\n{stale_sources}")


def check_nothing_left_behind(purged: bool):
    if installed_cas_packages():
        TestRun.fail(f"Packages left installed: {installed_cas_packages()}")

    # the second letter of the status is the actual state, 'n' meaning not installed
    leftover_state = {
        name: status for name, (status, _) in cas_packages_state().items()
        if status[1] != "n" and not (status == "rc" and name == main_package and not purged)
    }
    if leftover_state:
        TestRun.fail(f"Packages left in an unexpected state: {leftover_state}")

    leftover_modules = TestRun.executor.run("find /lib/modules -name 'cas_*.ko*'").stdout.strip()
    if leftover_modules:
        TestRun.fail(f"CAS modules left on disk:\n{leftover_modules}")

    if f"{dkms_module}/" in dkms_status():
        TestRun.fail(f"CAS modules still registered in DKMS:\n{dkms_status()}")

    leftover_paths = TestRun.executor.run(
        f"ls -d /usr/src/{dkms_module}-* /var/lib/dkms/{dkms_module} "
        f"/usr/lib/opencas /var/lib/opencas 2>/dev/null"
    ).stdout.strip()
    if leftover_paths:
        TestRun.fail(f"Paths left behind:\n{leftover_paths}")

    config_left = TestRun.executor.run("test -e /etc/opencas/opencas.conf").exit_code == 0
    if purged and config_left:
        TestRun.fail("Configuration left behind after purge")
    if not purged and not config_left:
        TestRun.fail("Configuration was removed without being asked to purge it")

    if service_links():
        TestRun.fail(f"Service links left behind: {service_links()}")

    if not local_fs_target_starts():
        TestRun.fail("local-fs.target can no longer be started")


def check_initramfs_omits_modules():
    """The tools package tells dracut to keep the modules out of the initramfs."""
    kernel = running_kernel()

    if TestRun.executor.run(f"update-initramfs -u -k {kernel}").exit_code != 0:
        TestRun.fail(f"Initramfs for {kernel} could not be rebuilt")

    lister = "lsinitrd" if TestRun.executor.run("which lsinitrd").exit_code == 0 else "lsinitramfs"
    contents = TestRun.executor.run_expect_success(f"{lister} /boot/initrd.img-{kernel}").stdout
    if re.search(r"cas_(cache|bd)\.ko", contents):
        TestRun.fail("CAS modules were put into the initramfs")


def purge_cas():
    """Leave no CAS packages, modules, DKMS registration or service links behind."""
    TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
    TestRun.executor.run(
        f"dpkg-query --show --showformat='${{Package}}\\n' '{main_package}*' 2>/dev/null | "
        f"xargs --no-run-if-empty dpkg --purge --force-depends --force-remove-reinstreq"
    )
    for module in (dkms_module, legacy_modules_package):
        TestRun.executor.run(
            f"dkms status -m {module} 2>/dev/null | cut -d, -f1 | cut -d: -f1 | sort -u | "
            f"while IFS=/ read -r m v; do [ -n \"$v\" ] && dkms remove -m \"$m\" -v \"$v\" --all; done"
        )
        remove(f"/var/lib/dkms/{module}", recursive=True, force=True, ignore_errors=True)
    # the glob covers the sources of both module names
    TestRun.executor.run(f"rm -rf /usr/src/{dkms_module}-* /usr/lib/opencas /var/lib/opencas")
    TestRun.executor.run(
        r"find /lib/modules \( -name 'cas_*.ko*' -o -path '*block/opencas*' \) -delete"
    )
    TestRun.executor.run(
        "find /etc/systemd/system -name 'open-cas*.service' -delete; "
        "find /var/lib/systemd/deb-systemd-helper-enabled -name 'open-cas*' -delete; "
        "systemctl daemon-reload"
    )
    TestRun.executor.run(
        "for k in $(ls /lib/modules); do "
        "[ -e /lib/modules/$k/modules.dep ] && depmod -a $k; done"
    )


def setup_packaging_test():
    require_deb_distro()
    require_dkms()
    prepare_sources()
    purge_cas()


def install(variant: str):
    output = apt_get("install", packages_of(variant))
    if output.exit_code != 0:
        TestRun.fail(f"Installing the {variant} packages failed:\n{output.stdout}\n{output.stderr}")


@pytest.fixture(autouse=True)
def leave_no_installation_behind():
    """
    Every test installs packages and must not hand them to the next one: the
    order tests run in is not fixed and they may not even run on the same DUT,
    so each cleans up after itself rather than relying on a test that does.
    """
    built_sets.clear()
    yield
    built_sets.clear()

    if TestRun.executor.run("which dpkg").exit_code == 0:
        purge_cas()
        remove(packages_root, recursive=True, force=True, ignore_errors=True)


@pytest.mark.os_dependent
def test_deb_packaging_build():
    """
    title: DEB packaging produces the expected packages.
    description: |
      Build the binary packages and check each carries what it is meant to:
      the tools, and the module sources DKMS builds on the target, tied
      together by version.
    pass_criteria:
      - exactly the tools and the modules packages are produced
      - the tools package is architecture specific, the modules one is not
      - the tools package requires the modules package of the same version
      - the modules package ships DKMS sources of its own version, no binaries
    """

    with TestRun.step("Prepare sources"):
        require_deb_distro()
        prepare_sources()

    with TestRun.step("Build the packages"):
        packages = split_packages(build_variant("current"))
        tools, modules = packages[main_package], packages[modules_package]
        version = upstream_version(modules)
        TestRun.LOGGER.info(f"Built version: {package_field(modules, 'Version')}")

        if not version.startswith(variant_version("current")):
            TestRun.fail(f"Packages are version {version}, sources are {variant_version('current')}")

    with TestRun.step("Check the architectures"):
        native = TestRun.executor.run_expect_success("dpkg --print-architecture").stdout.strip()

        if package_field(tools, "Architecture") != native:
            TestRun.fail(f"Tools package should be {native}, is {package_field(tools, 'Architecture')}")
        if package_field(modules, "Architecture") != "all":
            TestRun.fail(
                f"DKMS modules package should be 'all', "
                f"is {package_field(modules, 'Architecture')}"
            )

    with TestRun.step("Check the dependencies"):
        tools_depends = package_field(tools, "Depends")
        required = f"{modules_package} (= {package_field(modules, 'Version')})"
        if required not in tools_depends:
            TestRun.fail(f"Tools package should depend on '{required}', depends on: {tools_depends}")

        if not re.search(r"\bdkms\b", package_field(modules, "Depends")):
            TestRun.fail(
                f"Modules package does not depend on dkms: {package_field(modules, 'Depends')}"
            )

        # the package the DKMS sources were shipped in before has to be taken
        # out, or its copy of the modules would stay registered in DKMS
        for field in ["Conflicts", "Replaces"]:
            if legacy_modules_package not in package_field(modules, field):
                TestRun.fail(
                    f"Modules package should list {legacy_modules_package} in {field}: "
                    f"{package_field(modules, field) or 'none'}"
                )

    with TestRun.step("Check the tools package contents"):
        tools_files = package_files(tools)
        for expected in ["/usr/sbin/casadm", "/usr/sbin/casctl", "/etc/opencas/opencas.conf"]:
            if expected not in tools_files:
                TestRun.fail(f"Tools package does not contain {expected}")
        if any(re.search(r"\.ko(\.\w+)?$", f) for f in tools_files):
            TestRun.fail("Tools package contains kernel modules")

    with TestRun.step("Check the modules package contents"):
        modules_files = package_files(modules)
        sources_dir = f"/usr/src/{dkms_module}-{version}"

        outside = [f for f in modules_files
                   if f.startswith("/usr/src/") and f != "/usr/src/"
                   and not f.startswith(f"{sources_dir}/")]
        if outside or f"{sources_dir}/dkms.conf" not in modules_files:
            TestRun.fail(f"Module sources are not in {sources_dir}: {outside or modules_files}")

        binaries = [f for f in modules_files if re.search(r"\.(ko|o|mod\.c|cmd)$", f)]
        if binaries:
            TestRun.fail(f"Modules package ships build artifacts: {binaries}")

        dkms_conf = TestRun.executor.run_expect_success(
            f"dpkg-deb --fsys-tarfile {modules} | tar -xO .{sources_dir}/dkms.conf"
        ).stdout
        if f'PACKAGE_VERSION="{version}"' not in dkms_conf:
            TestRun.fail(f"dkms.conf is not for version {version}:\n{dkms_conf}")
        if "AUTOINSTALL=yes" not in dkms_conf:
            TestRun.fail("dkms.conf does not rebuild the modules for newly installed kernels")


@pytest.mark.os_dependent
def test_deb_packaging_build_debug():
    """
    title: DEB packaging produces debug symbols on request.
    description: |
      Build the packages with debug information and check a debug symbols
      package comes with them that matches the tools it is for.
    pass_criteria:
      - a debug symbols package is produced alongside the two packages
      - it carries the debug information of the casadm binary shipped
    """

    with TestRun.step("Prepare sources"):
        require_deb_distro()
        prepare_sources()

    with TestRun.step("Build the packages with debug information"):
        packages = build_variant("current", debug=True)
        tools = split_packages(packages)[main_package]

        dbgsym = [p for p in packages if package_name(p) == f"{main_package}-dbgsym"]
        if not dbgsym:
            TestRun.fail(
                f"No debug symbols package produced: {[os.path.basename(p) for p in packages]}"
            )

    with TestRun.step("Check the debug symbols match the casadm shipped"):
        extract_dir = os.path.join(packages_root, "casadm")
        create_directory(extract_dir, parents=True)
        TestRun.executor.run_expect_success(f"dpkg-deb --extract {tools} {extract_dir}")
        build_id = TestRun.executor.run_expect_success(
            f"readelf --notes {extract_dir}/usr/sbin/casadm | "
            f"awk '/Build ID/ {{print $3}}'"
        ).stdout.strip()

        if not build_id:
            TestRun.fail("casadm carries no build ID to match debug symbols against")

        debug_file = f"/usr/lib/debug/.build-id/{build_id[:2]}/{build_id[2:]}.debug"
        if debug_file not in package_files(dbgsym[0]):
            TestRun.fail(f"Debug symbols package has no {debug_file} for casadm")


@pytest.mark.os_dependent
def test_deb_packaging_build_from_source_package():
    """
    title: DEB source package builds on its own.
    description: |
      Generate the source package and build the binary packages from it alone,
      the way a distribution or a PPA would, without the git tree around it.
    pass_criteria:
      - the source package is generated
      - it unpacks and builds the same two binary packages at the same version
    """

    with TestRun.step("Prepare sources"):
        require_deb_distro()
        prepare_sources()

    source_dir = os.path.join(packages_root, "source")
    remove(source_dir, recursive=True, force=True, ignore_errors=True)
    create_directory(source_dir, parents=True)

    with TestRun.step("Generate the source package"):
        pckgen = os.path.join(TestRun.usr.working_dir, "tools", "pckgen.sh")
        TestRun.executor.run_expect_success(
            f"{pckgen} dsc --output-dir {source_dir} {TestRun.usr.working_dir}"
        )
        dsc = TestRun.executor.run_expect_success(f"ls {source_dir}/*.dsc").stdout.strip()

    with TestRun.step("Build the binary packages from it"):
        TestRun.executor.run_expect_success(
            f"cd {source_dir} && dpkg-source --extract {dsc} unpacked"
        )
        output = TestRun.executor.run(
            f"cd {source_dir}/unpacked && dpkg-buildpackage --build=binary -us -uc"
        )
        if output.exit_code != 0:
            TestRun.fail(f"Building from the source package failed:\n{output.stderr[-4000:]}")

    with TestRun.step("Check the packages built"):
        packages = split_packages(get_packages_list("deb", source_dir))
        dsc_version = TestRun.executor.run_expect_success(
            f"awk '/^Version:/ {{print $2}}' {dsc}"
        ).stdout.strip()

        for package in packages.values():
            if package_field(package, "Version") != dsc_version:
                TestRun.fail(
                    f"{os.path.basename(package)} is not the version of the source "
                    f"package ({dsc_version})"
                )


@pytest.mark.os_dependent
@pytest.mark.parametrize("method", ["remove", "purge"])
def test_deb_packaging_install_uninstall(method):
    """
    title: Install and uninstall Open CAS DEB packages.
    description: |
      Install the packages, check DKMS built the modules for every installed
      kernel and CAS is usable, then uninstall and check nothing is left
      behind - except for the configuration, when it was not asked to be purged.
    pass_criteria:
      - the packages install, DKMS installs the modules for every kernel
      - the modules load, the services are enabled, the initramfs omits CAS
      - uninstalling removes every package, module, DKMS registration and service
      - the configuration is kept on remove and deleted on purge
      - local-fs.target can still be started afterwards
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step("Install the packages"):
        install("current")
        version = upstream_version(packages_of("current")[0])

    with TestRun.step("Check DKMS installed the modules for every kernel"):
        check_modules_for_all_kernels(version)

    with TestRun.step("Check CAS is usable"):
        if not modules_load():
            TestRun.fail("CAS modules could not be loaded")
        if installed_module_version() != version:
            TestRun.fail(f"Loaded module is {installed_module_version()}, expected {version}")

        if not services_enabled():
            TestRun.fail(f"CAS services are not enabled: {service_links()}")

        # Leaves the Python bytecode cache behind, as any real use of casctl does.
        TestRun.executor.run_expect_success("casctl --help")

    with TestRun.step("Check the initramfs is built without CAS"):
        check_initramfs_omits_modules()

    with TestRun.step(f"Uninstall ({method})"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        output = apt_get(method, [main_package, modules_package])
        if output.exit_code != 0:
            TestRun.fail(f"Uninstalling ({method}) failed:\n{output.stdout}\n{output.stderr}")

    with TestRun.step("Check nothing is left behind"):
        check_nothing_left_behind(purged=(method == "purge"))


@pytest.mark.os_dependent
def test_deb_packaging_reinstall():
    """
    title: Reinstalling the same version of the packages works.
    description: |
      Reinstalling the installed version rebuilds the modules with DKMS over
      the ones already there, and uninstalling without purging and installing
      again restores the installation - including the enabled services.
    pass_criteria:
      - a reinstall succeeds and leaves working modules for every kernel
      - installing again after remove re-enables the services
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step("Install the packages"):
        install("current")
        version = upstream_version(packages_of("current")[0])

    with TestRun.step("Reinstall the same version"):
        output = apt_get("install", packages_of("current"), "--reinstall")
        if output.exit_code != 0:
            TestRun.fail(f"Reinstall failed:\n{output.stdout}\n{output.stderr}")

        check_modules_for_all_kernels(version)
        if not modules_load():
            TestRun.fail("CAS modules could not be loaded after the reinstall")

    with TestRun.step("Remove without purging and install again"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        output = apt_get("remove", [main_package, modules_package])
        if output.exit_code != 0:
            TestRun.fail(f"Remove failed:\n{output.stdout}\n{output.stderr}")

        install("current")

    with TestRun.step("Check the installation is restored"):
        check_modules_for_all_kernels(version)
        if not modules_load():
            TestRun.fail("CAS modules could not be loaded after installing again")
        if not services_enabled():
            TestRun.fail(f"CAS services are not enabled after installing again: {service_links()}")


@pytest.mark.os_dependent
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_deb_packaging_version_change(direction):
    """
    title: Upgrade and downgrade Open CAS DEB packages.
    description: |
      Move between two versions in both directions and check the result is a
      working installation of the expected version, with nothing of the other
      version left and the local configuration kept.
    pass_criteria:
      - the transaction succeeds and the expected version ends up installed
      - DKMS has only that version, installed for every kernel
      - the CAS modules of that version load
      - the services stay enabled and the edited configuration is kept
    """

    start, target = ("current", "next") if direction == "upgrade" else ("next", "current")
    config_marker = "# edited by test_deb_packaging_version_change"

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step(f"Install the starting packages ({start})"):
        install(start)
        TestRun.executor.run_expect_success(
            f"echo '{config_marker}' >> /etc/opencas/opencas.conf"
        )

    with TestRun.step(f"{direction.capitalize()} to {target}"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        options = "--allow-downgrades" if direction == "downgrade" else ""
        output = apt_get("install", packages_of(target), options)
        if output.exit_code != 0:
            TestRun.fail(f"{direction.capitalize()} to {target} failed:\n{output.stdout}")

    with TestRun.step("Check the resulting installation"):
        expected_version = upstream_version(packages_of(target)[0])
        if not expected_version.startswith(variant_version(target)):
            TestRun.fail(f"Built {expected_version}, expected a {variant_version(target)} build")

        installed = installed_cas_packages()
        expected = sorted(
            f"{name} {expected_version}-1" for name in [main_package, modules_package]
        )
        if installed != expected:
            TestRun.fail(f"Expected {expected} to be installed, got: {installed}")

        check_modules_for_all_kernels(expected_version)

        if not modules_load():
            TestRun.fail(f"CAS modules do not load after {direction} to {target}")
        if installed_module_version() != expected_version:
            TestRun.fail(
                f"Loaded module is {installed_module_version()}, expected {expected_version}"
            )

        if not services_enabled():
            TestRun.fail(f"CAS services were disabled by the {direction}: {service_links()}")

        if TestRun.executor.run(
            f"grep -qx '{config_marker}' /etc/opencas/opencas.conf"
        ).exit_code != 0:
            TestRun.fail(f"The {direction} discarded the edited configuration")


@pytest.mark.os_dependent
def test_deb_packaging_tools_require_matching_modules():
    """
    title: The tools cannot be upgraded without the modules.
    description: |
      casadm talks to the kernel module through an interface that changes
      between versions, so the tools package requires the modules package of
      exactly its own version. Upgrading the tools alone has to be refused.
    pass_criteria:
      - the transaction is refused
      - the originally installed packages are untouched and still work
    """

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()

    with TestRun.step("Install the packages"):
        install("current")
        installed_before = installed_cas_packages()

    with TestRun.step("Try to upgrade the tools package alone"):
        tools_next = split_packages(build_variant("next"))[main_package]
        output = apt_get("install", [tools_next])

        if output.exit_code == 0:
            TestRun.fail(
                f"Upgrading the tools without the modules was allowed, "
                f"leaving: {installed_cas_packages()}"
            )

    with TestRun.step("Check the installed packages were left untouched"):
        if installed_cas_packages() != installed_before:
            TestRun.fail(
                f"Refused transaction still changed what is installed:\n"
                f"before: {installed_before}\nafter:  {installed_cas_packages()}"
            )
        if not modules_load():
            TestRun.fail("CAS modules no longer load after the refused transaction")


@pytest.mark.os_dependent
def test_deb_packaging_dkms_builds_for_new_kernel():
    """
    title: The modules are built for a kernel installed after CAS.
    description: |
      A kernel installed later runs the DKMS kernel hook, which has to build
      and install the CAS modules for it. Stood in for by removing the modules
      of the running kernel and running the hook for it the way a kernel
      package installation does.
    pass_criteria:
      - the kernel hook installs the modules for that kernel again
      - the modules load
    """

    kernel_hook = "/etc/kernel/postinst.d/dkms"

    with TestRun.step("Prepare sources and clean the DUT"):
        setup_packaging_test()
        if TestRun.executor.run(f"test -x {kernel_hook}").exit_code != 0:
            pytest.skip(f"{kernel_hook} is not there to rebuild modules for new kernels")

    with TestRun.step("Install the packages"):
        install("current")
        version = upstream_version(packages_of("current")[0])
        kernel = running_kernel()

    with TestRun.step(f"Remove the modules of {kernel} from DKMS"):
        TestRun.executor.run("rmmod cas_cache; rmmod cas_bd")
        TestRun.executor.run_expect_success(
            f"dkms remove -m {dkms_module} -v {version} -k {kernel}"
        )
        if kernel in dkms_installed_kernels(version) or module_version_on_disk(kernel):
            TestRun.fail(f"Modules for {kernel} are still installed:\n{dkms_status()}")

    with TestRun.step("Run the kernel installation hook"):
        output = TestRun.executor.run(f"{kernel_hook} {kernel}")
        if output.exit_code != 0:
            TestRun.fail(f"The kernel hook failed:\n{output.stdout}\n{output.stderr}")

    with TestRun.step("Check the modules are back"):
        if kernel not in dkms_installed_kernels(version):
            TestRun.fail(f"DKMS did not install the modules for {kernel}:\n{dkms_status()}")
        if module_version_on_disk(kernel) != version:
            TestRun.fail(f"cas_cache for {kernel} is {module_version_on_disk(kernel)}")
        if not modules_load():
            TestRun.fail(f"CAS modules do not load after the rebuild for {kernel}")
