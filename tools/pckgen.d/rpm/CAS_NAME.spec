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
# Kernel modules are DKMS source, built on the target at install time, so
# the build host needs no kernel-devel. The opencas_exporter is an optional
# subpackage (%%bcond_with exporter below).


%global __python %{__python3}
<DEBUG_PACKAGE>
# Build the opencas_exporter (Prometheus) subpackage. Off by default — it
# pulls in a golang build dependency and go module download. Enable with:
#   rpmbuild --with exporter   (or: ./tools/pckgen.sh rpm --with-exporter)
%bcond_with exporter

Name:          <CAS_NAME>
Version:       <CAS_VERSION>
Release:       1%{?dist}
Summary:       Open Cache Acceleration Software
Group:         System
License:       <CAS_LICENSE_NAME>
URL:           <CAS_HOMEPAGE>
Source0:       https://github.com/Open-CAS/<CAS_NAME>/releases/download/v%{version}/%{name}-%{version}.tar.gz
Packager:      秦凡东 <qinfandong@kylinos.cn>
BuildRequires: coreutils
BuildRequires: gcc
BuildRequires: make
%if %{with exporter}
BuildRequires: golang
%endif
Requires:      %{name}-modules = %{version}-%{release}
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


%package modules
Summary:    Open Cache Acceleration Software kernel modules (DKMS source)
Group:      System
BuildArch:  noarch
Requires:   dkms
%description modules
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains the DKMS source tree for the CAS kernel modules.
The modules are compiled and installed on the target system by DKMS for
the running kernel, so no prebuilt kernel modules are shipped here.


%if %{with exporter}
%package exporter
Summary:    Open CAS Prometheus exporter
Group:      System
%description exporter
Open CAS Prometheus exporter. Collects cache, core and IO-class telemetry
from the running CAS kernel modules via Generic Netlink and serves it on
:9493/metrics. Statically linked; requires the CAS kernel modules to be
loaded to report anything other than opencas_up=0.
%endif


%prep
%setup -q


%build
# Only userspace is built here. Kernel modules are built on the target via DKMS.
(cd tools/; ./cas_version_gen.sh build)
make -C utils
%if %{with exporter}
make -C extra
%endif
<MAKE_BUILD>


%install
rm -rf $RPM_BUILD_ROOT

# Install userspace before scrubbing the DKMS source tree below.
(cd casadm; make install_files DESTDIR="$RPM_BUILD_ROOT")
(cd utils;  make install_files DESTDIR="$RPM_BUILD_ROOT")
%if %{with exporter}
(cd extra;  make install_files DESTDIR="$RPM_BUILD_ROOT")
%endif

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
DKMS_TREE=%{name}-modules-%{version}
DKMS_ROOT="$RPM_BUILD_ROOT/usr/src/$DKMS_TREE"
install -d -m 755 "$DKMS_ROOT" "$DKMS_ROOT/.metadata" "$DKMS_ROOT/tools"
cp -a .metadata/*                       "$DKMS_ROOT/.metadata/"  2>/dev/null || :
cp -a modules                           "$DKMS_ROOT/"
cp -a ocf                               "$DKMS_ROOT/"
cp -a utils                             "$DKMS_ROOT/"
cp -a tools/cas_version_gen.sh tools/helpers.mk "$DKMS_ROOT/tools/"
cp -a configure.d                       "$DKMS_ROOT/"            2>/dev/null || :
cp -a configure Makefile LICENSE version "$DKMS_ROOT/"

# dkms.conf: <CAS_NAME>/<CAS_VERSION>/<CAS_MODULES_DIR> are substituted by
# pckgen.sh; $kernelver is a DKMS var (literal via the quoted heredoc).
# No -j here: dkms prepends "make -j<ncpu> ..." (get_num_cpus), and a later
# bare "-j" would win (last -j = unlimited) and clobber the nproc count.
cat > "$DKMS_ROOT/dkms.conf" <<'EOF'
PACKAGE_NAME="<CAS_NAME>-modules"
PACKAGE_VERSION="<CAS_VERSION>"
BUILT_MODULE_NAME[0]="cas_cache"
BUILT_MODULE_LOCATION[0]="modules/cas_cache/"
DEST_MODULE_LOCATION[0]="/<CAS_MODULES_DIR>"
BUILT_MODULE_NAME[1]="cas_bd"
BUILT_MODULE_LOCATION[1]="modules/cas_bd/"
DEST_MODULE_LOCATION[1]="/<CAS_MODULES_DIR>"
PRE_BUILD="./configure"
MAKE[0]="make -C modules/ KERNEL_VERSION=$kernelver"
AUTOINSTALL=yes
EOF


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


%post modules
# Register the DKMS tree. --rpm_safe_upgrade keeps the add+remove pair safe
# across RPM upgrades (dkms(8); also on %preun remove). || : — dkms add
# returns 3 on re-add (reinstall), not a real failure.
dkms add     -m %{name}-modules -v %{version} --rpm_safe_upgrade || :
# Build for the running kernel. No || : — fail visibly if kernel-devel is
# missing (dkms returns 0 for "already installed", so reinstalls still work).
dkms install -m %{name}-modules -v %{version} -k "$(uname -r)" || exit 1
# Best-effort build for other installed kernels (skip those without
# kernel-devel) so a fallback kernel isn't left without modules.
for kver in $(ls /lib/modules 2>/dev/null | grep -vxF "$(uname -r)"); do
    [ -d "/lib/modules/$kver/build" ] || continue
    dkms install -m %{name}-modules -v %{version} -k "$kver" || :
done

%preun modules
# Drop dkms's archived old-kmod .ko (original_module) before `dkms remove`
# so it doesn't restore them as orphans (the old kmod package is gone).
rm -rf /var/lib/dkms/%{name}-modules/original_module 2>/dev/null || :
dkms remove  -m %{name}-modules -v %{version} --all --rpm_safe_upgrade || :

%posttrans modules
# kmod->dkms upgrade orphans the old open-cas-linux-modules_k<kernelver>
# (name varies per kernel, can't Obsoletes). Can't rpm -e inside this
# transaction (rpmdb lock), so a detached worker (setsid) waits for the PM
# (dnf/zypper/yum) to exit, then rpm -e --nodeps --noscripts the orphans
# (--noscripts: old %preun fails on archived .ko; --nodeps: orphan has no
# deps) + deletes stale weak-updates symlinks. Guarded (no-op on fresh).
if [ -n "$(rpm -qa "open-cas-linux-modules_k*" 2>/dev/null)" ]; then
    ( setsid sh -c '
        while pgrep -x dnf >/dev/null 2>&1 || pgrep -x zypper >/dev/null 2>&1 || pgrep -x yum >/dev/null 2>&1; do sleep 3; done
        rpm -e --nodeps --noscripts $(rpm -qa "open-cas-linux-modules_k*") >/dev/null 2>&1 || :
        # --noscripts skipped the old %postun (weak-modules --remove-modules);
        # clean its dangling weak-updates/block/opencas symlinks.
        find /lib/modules -type l -path "*/weak-updates/block/opencas/*" -delete 2>/dev/null || :
    ' </dev/null >/dev/null 2>&1 ) &
fi


%files
%defattr(-, root, root, 755)
%license LICENSE
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


%files modules
%defattr(-, root, root, 755)
/usr/src/%{name}-modules-%{version}/


%if %{with exporter}
%files exporter
%defattr(-, root, root, 755)
/usr/bin/opencas_exporter
/usr/lib/systemd/system/opencas_exporter.service
%endif


%changelog
* Wed Aug 05 2026 秦凡东 <qinfandong@kylinos.cn> - 26.09-1
- Build kernel modules via DKMS on the target system
- Split opencas_exporter into a conditional subpackage (--with exporter)

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
