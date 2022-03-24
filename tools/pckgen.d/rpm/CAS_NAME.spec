#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

#
# This is a template SPEC file for generating OpenCAS RPMs automatically.
# It contains tags in form of <TAG> which are substituted with particular
# values in the build time.
#


%global __python %{__python3}
%define debug_package %{nil}
%define kver %(uname -r)
%define kver_filename k%{expand:%(kname="%{kver}"; echo "${kname%.*}" | sed -r "y/-/_/;")}


Name:       <CAS_NAME>
Version:    <CAS_VERSION>
Release:    1%{?dist}
Summary:    Open Cache Acceleration Software
Group:      System
Vendor:     Intel Corporation
License:    <CAS_LICENSE_NAME>
URL:        <CAS_HOMEPAGE>
Source0:    https://github.com/Open-CAS/open-cas-linux/releases/download/v%{version}/%{name}-%{version}.tar.gz
Packager:   <PACKAGE_MAINTAINER>
BuildRequires:  coreutils, gawk, gcc, kernel-devel, kernel-headers, make
Requires:   <CAS_NAME>-modules-%{version}, python3, sed, python3-packaging, python3-PyYAML
%description
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains tools and utilities for managing CAS and monitor
running cache instances.


%package    modules_%{kver_filename}
Summary:    Open Cache Acceleration Software kernel modules
Group:      System
Requires:   kmod
Provides:   <CAS_NAME>-modules-%{version}
%description    modules_%{kver_filename}
Open Cache Acceleration Software (Open CAS) is an open source project
encompassing block caching software libraries, adapters, tools and more.
The main goal of this cache acceleration software is to accelerate a
backend block device(s) by utilizing a higher performance device(s).
This package contains only CAS kernel modules.


%prep
%setup -q


%build
./configure
%make_build


%install
rm -rf $RPM_BUILD_ROOT
/usr/bin/make install_files DESTDIR=$RPM_BUILD_ROOT


%post
systemctl daemon-reload
systemctl -q enable open-cas-shutdown
systemctl -q enable open-cas

%preun
if [ $1 -eq 0 ]; then
    systemctl -q disable open-cas-shutdown
    systemctl -q disable open-cas

    rm -rf /lib/opencas/{__pycache__,*.py[co]} &>/dev/null
fi

%postun
if [ $1 -eq 0 ]; then
    systemctl daemon-reload
fi


%post modules_%{kver_filename}
depmod
. /etc/os-release
# Determine the exact location of installed modules to add them to weak-modules
for file in $(rpm -ql $(rpm -qa | grep <CAS_NAME>-modules)); do
if [[ "$file" =~ cas_.*\.ko$ ]]; then
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
        realpath $(find /lib/modules/*/extra/block/opencas/ -name "cas_*.ko") >/var/run/rpm-open-cas-linux-modules
    fi
fi

%postun modules_%{kver_filename}
if [ $1 -eq 0 ]; then
    . /etc/os-release
    if [[ ! "$ID_LIKE" =~ suse|sles ]]; then
        modules=( $(cat /var/run/rpm-open-cas-linux-modules) )
        rm -f /var/run/rpm-open-cas-linux-modules
        printf "%s\n" "${modules[@]}" | weak-modules --no-initramfs --remove-modules
    fi
    depmod
fi


%files
%defattr(-, root, root, 755)
%license LICENSE
%doc README.md
%dir /etc/opencas/
%dir /lib/opencas/
%dir /var/lib/opencas
%config /etc/opencas/opencas.conf
/etc/opencas/ioclass-config.csv
/etc/dracut.conf.d/opencas.conf
/var/lib/opencas/cas_version
/lib/opencas/casctl
/lib/opencas/open-cas-loader
/lib/opencas/opencas.py
/lib/udev/rules.d/60-persistent-storage-cas-load.rules
/lib/udev/rules.d/60-persistent-storage-cas.rules
/sbin/casadm
/sbin/casctl
/usr/lib/systemd/system-shutdown/open-cas.shutdown
/usr/lib/systemd/system/open-cas-shutdown.service
/usr/lib/systemd/system/open-cas.service
/usr/share/man/man5/opencas.conf.5.gz
/usr/share/man/man8/casadm.8.gz
/usr/share/man/man8/casctl.8.gz
%ghost /var/log/opencas.log
%ghost /lib/opencas/opencas.pyc
%ghost /lib/opencas/opencas.pyo
%ghost /lib/opencas/__pycache__

%files  modules_%{kver_filename}
%defattr(644, root, root, 755)
%license LICENSE
/lib/modules/%{kver}


%changelog
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
