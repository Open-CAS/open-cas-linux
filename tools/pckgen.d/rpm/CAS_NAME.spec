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
# Kernel modules are shipped as DKMS source and built on the target system
# at install time (mirrors the DEB packaging). The host that builds this RPM
# therefore does not need kernel-devel/kernel-headers; only the userspace
# tools (casadm, utils) are compiled here. The Prometheus exporter
# (opencas_exporter) is an optional subpackage, see %bcond_with exporter
# below.


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
Packager:      Qin Fandong <qinfandong@kylinos.cn>
BuildRequires: coreutils
BuildRequires: gawk
BuildRequires: gcc
BuildRequires: make
%if %{with exporter}
BuildRequires: golang
%endif
BuildRequires: procps
BuildRequires: python3
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
Requires(post): dkms
Requires(preun): dkms
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

# Install userspace first (built in %build). Done before cleaning the DKMS
# source tree so the tree can be scrubbed of build artifacts without affecting
# the already-installed userspace files.
(cd casadm; make install_files DESTDIR="$RPM_BUILD_ROOT")
(cd utils;  make install_files DESTDIR="$RPM_BUILD_ROOT")
%if %{with exporter}
(cd extra;  make install_files DESTDIR="$RPM_BUILD_ROOT")
%endif

# Scrub build artifacts so the DKMS source tree is source-only:
#  - casadm build synced OCF headers into modules/; distsync reverses it
#    (ocf inc/distclean are pure file ops, no kernel headers needed).
#  - utils manpages (.gz) were generated in %build; remove from the source.
#  - strip any kernel build objects from modules/ in case the source tarball
#    shipped them (archive_prepare's distclean needs KERNEL_DIR and is a
#    non-fatal no-op on a kernel-devel-free build host).
make -C modules distsync
make -C utils clean
find modules -type f \( -name '*.ko' -o -name '*.o' -o -name '*.cmd' \
    -o -name '*.mod.c' -o -name '*.mod' -o -name 'modules.order' \
    -o -name 'modules.builtin' \) -delete 2>/dev/null || :
rm -rf modules/.tmp_versions 2>/dev/null || :

# Regenerate version metadata (no build timestamp) for the DKMS source tree.
(cd tools/; ./cas_version_gen.sh)

# Install DKMS source tree (mirrors the DEB modules source package layout).
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

# dkms.conf (tokens <CAS_NAME>/<CAS_VERSION>/<CAS_MODULES_DIR> are substituted
# by pckgen.sh; $kernelver is a DKMS variable kept literal via the quoted
# heredoc so DKMS expands it per target kernel).
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
MAKE[0]="make -j -C modules/ KERNEL_VERSION=$kernelver"
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


# Register/build/install the DKMS module tree for the running kernel.
# --rpm_safe_upgrade (documented in dkms(8)) keeps upgrades safe across
# versions of this package; it is required on both the add and remove actions.
%post modules
dkms add     -m %{name}-modules -v %{version} --rpm_safe_upgrade || :
dkms install -m %{name}-modules -v %{version} || :

%preun modules
dkms remove  -m %{name}-modules -v %{version} --all --rpm_safe_upgrade || :


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
* Wed Aug 05 2026 Qin Fandong <qinfandong@kylinos.cn> - 26.09-1
- Build kernel modules via DKMS on the target system (like the DEB packaging)
- Split opencas_exporter into a conditional subpackage (--with exporter)

* Tue Apr 28 2026 Qin Fandong <qinfandong@kylinos.cn> - 26.06-1
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
