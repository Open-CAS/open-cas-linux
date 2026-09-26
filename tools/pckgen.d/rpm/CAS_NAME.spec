#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2025 Huawei Technologies
# Copyright(c) 2025 Brian J. Murrell
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

#
# This is a template SPEC file for generating OpenCAS RPMs automatically.
# It contains tags in form of <TAG> which are substituted with particular
# values in the build time.
#
# The kernel modules can be packaged in two ways, selected with the 'dkms'
# build conditional:
#
#   (default)              modules prebuilt for one specific kernel, shipped
#                          in a <CAS_NAME>-modules_k<kernel version> subpackage.
#                          The build host needs the matching kernel-devel.
#
#   rpmbuild --with dkms   the module sources, shipped as a DKMS source tree
#                          and built on the target at install time. It requires
#                          DKMS support on the target node.


%global __python %{__python3}
<DEBUG_PACKAGE>
# Ship the kernel modules as DKMS sources built on the target instead of
# modules prebuilt for a single kernel. Off by default. Enable with:
#   rpmbuild --with dkms   (or: ./tools/pckgen.sh rpm --with-dkms)
%bcond_with dkms
%if %{without dkms}
%define kver <KVER>
# Following define takes kernel version, cuts everything after (and including)
# second hyphen (-), and then cuts the architecture (including 'noarch') part.
# It's the only package version variant that is accepted by RPM spec.
%define kver_pkg %{expand:%(kpkg="%{kver}"; for i in $(seq 2 $(grep -o '-' <<<$kpkg | grep -c .)); do kpkg="${kpkg%%-*}"; done; kpkg="${kpkg%%.$(uname -m)}"; echo "${kpkg%%.noarch}")}
%define kver_filename k%{expand:%(echo "%{kver}" | sed -r "y/-/_/;")}
%endif


Name:          <CAS_NAME>
Version:       <CAS_VERSION>
Release:       1%{?dist}
Summary:       Open Cache Acceleration Software
Group:         System
License:       <CAS_LICENSE_NAME>
URL:           <CAS_HOMEPAGE>
Source0:       https://github.com/Open-CAS/<CAS_NAME>/releases/download/v%{version}/%{name}-%{version}.tar.gz
Packager:      <PACKAGE_MAINTAINER>
BuildRequires: coreutils
BuildRequires: gawk
BuildRequires: gcc
BuildRequires: make
BuildRequires: procps
BuildRequires: python3
%if %{without dkms}
# Allow using different version of kernel-headers package (some distros requires it).
BuildRequires: kernel-headers
BuildRequires: <KERNEL_PKG> = %{kver_pkg}
BuildRequires: <KERNEL_DEVEL_PKG> = %{kver_pkg}
BuildRequires: <LIBELF_PKG>
BuildRequires: <UTIL_PKG>
%endif
# Required by name-and-version rather than as a package, because either module
# package can satisfy it. Switching between them then keeps the requirement
# satisfied inside the one transaction, instead of the erasure of the outgoing
# one taking these tools with it.
Requires:      <CAS_NAME>-modules-%{version}
Requires:      python3
Requires:      python3-PyYAML
Requires:      sed
%description
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains tools and utilities for managing CAS and monitor
running cache instances.


%if %{without dkms}
%package    modules_%{kver_filename}
Summary:    Open Cache Acceleration Software kernel modules
Group:      System
Requires:   kmod
Provides:   <CAS_NAME>-modules-%{version}
# The two ways of shipping the modules are alternatives, not one superseding
# the other, so they are mutually exclusive rather than obsoleting: installing
# either over the other has to be an explicit choice (dnf --allowerasing / dnf
# swap) and not something the solver does on its own during an upgrade. rpm
# applies this in both directions, so naming the DKMS package here is enough -
# the prebuilt package cannot be named, its name carries the kernel version.
Conflicts:  <CAS_NAME>-dkms
%description    modules_%{kver_filename}
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains only CAS kernel modules.
%else
%package dkms
Summary:    Open Cache Acceleration Software kernel modules (DKMS source)
Group:      System
BuildArch:  noarch
Requires:   dkms
Provides:   <CAS_NAME>-modules-%{version}
%description dkms
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains the DKMS source tree for the CAS kernel modules.
The modules are compiled and installed on the target system by DKMS for
the kernels installed there, so no prebuilt kernel modules are shipped here.
%endif


%prep
%setup -q


%build
%if %{without dkms}
if [ -e /lib/modules/%{kver}/build/Makefile ]; then
    export KERNEL_DIR=/lib/modules/%{kver}/build/
elif [ -e /usr/src/kernels/%{kver}/Makefile ]; then
    export KERNEL_DIR=/usr/src/kernels/%{kver}/
else
    echo "Kernel build tree for %{kver} not found" >&2
    exit 1
fi
./configure --kernel-dir $KERNEL_DIR
<MAKE_BUILD>
%else
# Only userspace is built here. Kernel modules are built on the target via DKMS.
(cd tools/; ./cas_version_gen.sh build)
make -C utils
<MAKE_BUILD_CASADM>
%endif


%install
rm -rf $RPM_BUILD_ROOT

%if %{without dkms}
/usr/bin/make install_files DESTDIR=$RPM_BUILD_ROOT KERNEL_VERSION=%{kver}
%else
# Install userspace before scrubbing the DKMS source tree below.
(cd casadm; make install_files DESTDIR="$RPM_BUILD_ROOT")
(cd utils;  make install_files DESTDIR="$RPM_BUILD_ROOT")

# Scrub build artifacts so the DKMS tree ships source-only: distsync reverses
# the OCF header sync into modules/, utils clean drops manpages, find strips
# any stray kernel build objects.
make -C modules distsync
make -C utils clean
find modules -type f \( -name '*.ko' -o -name '*.o' -o -name '*.cmd' \
    -o -name '*.mod.c' -o -name '*.mod' -o -name 'modules.order' \
    -o -name 'modules.builtin' \) -delete 2>/dev/null || :
rm -rf modules/.tmp_versions 2>/dev/null || :

# Regenerate version metadata (no build timestamp) for the DKMS source tree.
(cd tools/; ./cas_version_gen.sh)

# Install DKMS source tree.
DKMS_TREE=%{name}-%{version}
DKMS_ROOT="$RPM_BUILD_ROOT/usr/src/$DKMS_TREE"
install -d -m 755 "$DKMS_ROOT" "$DKMS_ROOT/.metadata" "$DKMS_ROOT/tools"
cp -a .metadata/*                       "$DKMS_ROOT/.metadata/"  2>/dev/null || :
cp -a modules                           "$DKMS_ROOT/"
cp -a ocf                               "$DKMS_ROOT/"
cp -a utils                             "$DKMS_ROOT/"
cp -a tools/cas_version_gen.sh tools/helpers.mk "$DKMS_ROOT/tools/"
cp -a configure.d                       "$DKMS_ROOT/"            2>/dev/null || :
cp -a configure Makefile LICENSE.md version "$DKMS_ROOT/"

# dkms.conf: <CAS_NAME>/<CAS_VERSION>/<CAS_MODULES_DIR> are substituted by
# pckgen.sh; $kernelver is a DKMS var (literal via the quoted heredoc).
# No -j here: dkms prepends "make -j<ncpu> ..." (get_num_cpus), and a later
# bare "-j" would win (last -j = unlimited) and clobber the nproc count.
# DKMS builds for a kernel that is not necessarily the running one, so the
# kernel has to be spelled out for './configure' as well - left to itself it
# probes the running kernel and generates a header for the wrong kernel API,
# which 'make' then refuses to build against.
cat > "$DKMS_ROOT/dkms.conf" <<'EOF'
PACKAGE_NAME="<CAS_NAME>"
PACKAGE_VERSION="<CAS_VERSION>"
BUILT_MODULE_NAME[0]="cas_cache"
BUILT_MODULE_LOCATION[0]="modules/cas_cache/"
DEST_MODULE_LOCATION[0]="/<CAS_MODULES_DIR>"
BUILT_MODULE_NAME[1]="cas_bd"
BUILT_MODULE_LOCATION[1]="modules/cas_bd/"
DEST_MODULE_LOCATION[1]="/<CAS_MODULES_DIR>"
DKMS_KERNEL_DIR="/lib/modules/$kernelver/build"
PRE_BUILD="./configure --kernel-dir $DKMS_KERNEL_DIR"
MAKE[0]="make -C modules/ KERNEL_VERSION=$kernelver KERNEL_DIR=$DKMS_KERNEL_DIR"
AUTOINSTALL=yes
EOF
%endif


%post
systemctl daemon-reload
systemctl -q enable open-cas-shutdown
systemctl -q enable open-cas

%preun
if [ $1 -eq 0 ]; then
    systemctl -q disable open-cas-shutdown
    systemctl -q disable open-cas

    rm -rf /usr/lib/opencas/{__pycache__,*.py[co]} &>/dev/null
fi

%postun
if [ $1 -eq 0 ]; then
    systemctl daemon-reload
fi


%if %{without dkms}
%post modules_%{kver_filename}
depmod -a %{kver}
. /etc/os-release
# Determine the exact location of installed modules to add them to weak-modules
for file in $(rpm -ql $(rpm -qa | grep <CAS_NAME>-modules)); do
if [[ "$file" =~ .*\.ko$ ]]; then
    # realpath to resolve any possible symlinks (needed for weak-modules)
    modules+=( $(realpath "$file") )
fi
done

if [[ ! "$ID_LIKE" =~ suse|sles ]]; then
    printf "%s\n" "${modules[@]}" | weak-modules --no-initramfs --add-modules
else
    for version in $(echo "${modules[@]}" | tr " " "\n" | cut -d"/" -f4 | sort | uniq); do
        # run depmod for all kernel versions for which the modules installed
        depmod $version
    done
fi

%preun modules_%{kver_filename}
if [ $1 -eq 0 ]; then
    . /etc/os-release
    if [[ ! "$ID_LIKE" =~ suse|sles ]]; then
        # Search for all CAS modules to remove them from weak-modules
        # Use realpath to resolve any possible symlinks (needed for weak-modules)
        realpath $(find /lib/modules/%{kver}/<CAS_MODULES_DIR> -name "*.ko") >/var/run/rpm-<CAS_NAME>-modules
    fi
fi

%postun modules_%{kver_filename}
if [ $1 -eq 0 ]; then
    . /etc/os-release
    if [[ ! "$ID_LIKE" =~ suse|sles ]]; then
        modules=( $(cat /var/run/rpm-<CAS_NAME>-modules) )
        rm -f /var/run/rpm-<CAS_NAME>-modules
        printf "%s\n" "${modules[@]}" | weak-modules --no-initramfs --remove-modules
    fi
    # The kernel package may have been uninstalled before Open CAS RPM
    if [ -e /lib/modules/%{kver}/modules.dep ]; then
        depmod -a %{kver}
    fi
fi
%else
%posttrans dkms
# In %posttrans rather than %post: when this replaces the prebuilt package in
# one transaction, that package is erased between the two, and dkms refuses to
# overwrite a module already installed at the same version - so in %post its
# modules would still be in the way, and the erase would then take away the
# ones dkms declined to replace.
# --rpm_safe_upgrade keeps the add+remove pair safe across RPM upgrades
# (dkms(8); also on %preun remove). || : — dkms add returns 3 on re-add
# (reinstall), not a real failure.
dkms add     -m %{name} -v %{version} --rpm_safe_upgrade || :
# Build for the running kernel. No || : — fail visibly if kernel-devel is
# missing (dkms returns 0 for "already installed", so reinstalls still work).
dkms install -m %{name} -v %{version} -k "$(uname -r)" || exit 1
# Best-effort build for other installed kernels (skip those without
# kernel-devel) so a fallback kernel isn't left without modules.
for kver in $(ls /lib/modules 2>/dev/null | grep -vxF "$(uname -r)"); do
    [ -d "/lib/modules/$kver/build" ] || continue
    dkms install -m %{name} -v %{version} -k "$kver" || :
done

# kmod->dkms upgrade orphans the old open-cas-linux-modules_k<kernelver>
# (name varies per kernel, can't Obsoletes). Can't rpm -e inside this
# transaction (rpmdb lock), so a detached worker (setsid) waits for the PM
# (dnf/zypper/yum) to exit, then rpm -e --nodeps --noscripts the orphans
# (--noscripts: old %preun fails on archived .ko; --nodeps: orphan has no
# deps) + deletes stale weak-updates symlinks. Guarded (no-op on fresh).
# Giving up the prebuilt modules is only safe once DKMS has modules of its own
# in place. A failed build above exits this scriptlet before the worker is even
# started, and the worker checks the state again for itself - between the two,
# a build that did not produce anything cannot end up taking the modules the
# system is currently using with it.
if [ -n "$(rpm -qa "open-cas-linux-modules_k*" 2>/dev/null)" ]; then
    ( setsid sh -c '
        while pgrep -x dnf >/dev/null 2>&1 || pgrep -x zypper >/dev/null 2>&1 || pgrep -x yum >/dev/null 2>&1; do sleep 3; done
        dkms status -m %{name} -v %{version} -k "$(uname -r)" 2>/dev/null | grep -q ": installed" || exit 0
        rpm -e --nodeps --noscripts $(rpm -qa "open-cas-linux-modules_k*") >/dev/null 2>&1 || :
        # --noscripts skipped the old %postun (weak-modules --remove-modules),
        # so clean up after it: drop its dangling weak-updates/block/opencas
        # symlinks and rebuild the module index, which still lists the files
        # just removed and would otherwise break modprobe and dracut.
        find /lib/modules -type l -path "*/weak-updates/block/opencas/*" -delete 2>/dev/null || :
        for kver in $(ls /lib/modules 2>/dev/null); do
            [ -e "/lib/modules/$kver/modules.dep" ] || continue
            depmod -a "$kver" 2>/dev/null || :
        done
    ' </dev/null >/dev/null 2>&1 ) &
fi

%preun dkms
# Drop dkms's archived old-kmod .ko (original_module) before `dkms remove`
# so it doesn't restore them as orphans (the old kmod package is gone).
rm -rf /var/lib/dkms/%{name}/original_module 2>/dev/null || :
dkms remove  -m %{name} -v %{version} --all --rpm_safe_upgrade || :
# dkms weak-links the built modules into kABI-compatible kernels it did not
# build for (/lib/modules/<kver>/weak-updates/), and `dkms remove` drops the
# built modules while leaving those symlinks behind. Dangling ones break
# dracut ("installkernel failed in module kernel-modules-extra"), which would
# outlive the package, so clear them and refresh the dependency lists.
find /lib/modules -path "*/weak-updates/*" -name "cas_*.ko*" -xtype l -delete 2>/dev/null || :
for kver in $(ls /lib/modules 2>/dev/null); do
    [ -e "/lib/modules/$kver/modules.dep" ] || continue
    depmod -a "$kver" 2>/dev/null || :
done

%endif


%files
%defattr(-, root, root, 755)
%license LICENSE.md
%doc README.md
%dir /etc/opencas/
%dir /usr/lib/opencas/
%dir /var/lib/opencas
%config /etc/opencas/opencas.conf
/etc/opencas/ioclass-config.csv
/etc/dracut.conf.d/opencas.conf
/var/lib/opencas/cas_version
/usr/lib/opencas/casctl
/usr/lib/opencas/open-cas-loader.py
/usr/lib/opencas/opencas.py
/usr/lib/udev/rules.d/60-persistent-storage-cas-load.rules
/usr/lib/udev/rules.d/60-persistent-storage-cas.rules
/usr/sbin/casadm
/usr/sbin/casctl
/usr/lib/systemd/system-shutdown/open-cas.shutdown
/usr/lib/systemd/system/open-cas-shutdown.service
/usr/lib/systemd/system/open-cas.service
/usr/share/man/man5/opencas.conf.5.gz
/usr/share/man/man8/casadm.8.gz
/usr/share/man/man8/casctl.8.gz
%ghost /var/log/opencas.log
%ghost /usr/lib/opencas/opencas.pyc
%ghost /usr/lib/opencas/opencas.pyo
%ghost /usr/lib/opencas/__pycache__

%if %{without dkms}
%files  modules_%{kver_filename}
%defattr(644, root, root, 755)
%license LICENSE.md
/lib/modules/%{kver}
%else
%files dkms
%defattr(-, root, root, 755)
/usr/src/%{name}-%{version}/
%endif


%changelog
* Wed Aug 05 2026 秦凡东 <qinfandong@kylinos.cn> - 26.09-1
- Add an option to ship the kernel modules as DKMS sources (--with dkms)
* Tue Apr 28 2026 秦凡东 <qinfandong@kylinos.cn> - 26.06-1
- Add opencas_exporter
* Mon Aug 25 2025 Rafal Stefanowski <rafal.stefanowski@huawei.com> - 25.03-1
* Thu Aug 7 2025 Brian J. Murrell <brian@interlinx.bc.ca> - 25.03-1
- Allow building RPM packages for different kernel versions
- Update dependencies
* Mon Mar 21 2022 Rafal Stefanowski <rafal.stefanowski@intel.com> - 22.03-1
- Update modules destination directory and permissions
- Add license to modules package
- Fix resolving of weak-modules symlinks
* Mon Nov 22 2021 Michal Mielewczyk <michal.mielewczyk@intel.com> - 21.06-1
- Update dependencies
* Mon Feb 8 2021 Rafal Stefanowski <rafal.stefanowski@intel.com> - 21.03-1
- Improve python files handling
* Tue Jan 5 2021 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.12-1
- Fix resolving modules path for weak-modules
* Fri Sep 11 2020 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.09-1
- SLES related modifications
- Add some missing info about a package
* Thu Jul 30 2020 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.09-1
- Improve adding and removing modules with weak-modules
* Wed Jun 10 2020 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.06-1
- Add cas_version file
- Join Release into Version
- Simplify prep setup
* Tue Feb 25 2020 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.3-1
- Minor improvements in SPEC file
- Update files list for releases > 20.1
* Thu Feb 06 2020 Rafal Stefanowski <rafal.stefanowski@intel.com> - 20.1-1
- Create this SPEC file for OpenCAS release 20.1
