#
# Copyright(c) 2012-2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

CASCTL_DIR = /lib/opencas
UDEVRULES_DIR = /lib/udev/rules.d
UDEV:=$(shell which udevadm)
SYSTEMCTL := $(shell which systemctl)

ifeq (, $(shell which systemctl))
define cas_install
	install -m 755 open-cas-shutdown /etc/init.d/open-cas-shutdown
	/sbin/chkconfig open-cas-shutdown on; service open-cas-shutdown start
endef
else
ifneq "$(wildcard /usr/lib/systemd/system)" ""
	SYSTEMD_DIR=/usr/lib/systemd/system
else
	SYSTEMD_DIR=/lib/systemd/system
endif
define cas_install
	install -m 644 open-cas-shutdown.service $(SYSTEMD_DIR)/open-cas-shutdown.service
	install -m 755 -d $(SYSTEMD_DIR)/../system-shutdown
	install -m 755 open-cas.shutdown $(SYSTEMD_DIR)/../system-shutdown/open-cas.shutdown
	$(SYSTEMCTL) daemon-reload
	$(SYSTEMCTL) -q enable open-cas-shutdown
endef
endif

# Just a placeholder when running make from parent dir without install/uninstall arg
default: ;

install:
	@echo "Installing Open-CAS utils"

	@install -m 755 -d $(CASCTL_DIR)
	@install -m 644 opencas.py $(CASCTL_DIR)/opencas.py
	@install -m 755 casctl $(CASCTL_DIR)/casctl
	@install -m 755 open-cas-loader $(CASCTL_DIR)/open-cas-loader
	@install -m 755 open-cas-mount-utility $(CASCTL_DIR)/open-cas-mount-utility

	@ln -fs $(CASCTL_DIR)/casctl /sbin/casctl

	@install -m 644 60-persistent-storage-cas-load.rules $(UDEVRULES_DIR)/60-persistent-storage-cas-load.rules
	@install -m 644 60-persistent-storage-cas.rules $(UDEVRULES_DIR)/60-persistent-storage-cas.rules

	@install -m 755 -d /usr/share/doc/opencas

	@$(UDEV) control --reload-rules

	@install -m 644 casctl.8 /usr/share/man/man8/casctl.8

	$(cas_install)

uninstall:
	@rm $(CASCTL_DIR)/opencas.py
	@rm $(CASCTL_DIR)/casctl
	@rm $(CASCTL_DIR)/open-cas-loader
	@rm $(CASCTL_DIR)/open-cas-mount-utility
	@rm -rf $(CASCTL_DIR)

	@rm /sbin/casctl

	@rm /usr/share/man/man8/casctl.8

	@rm /lib/udev/rules.d/60-persistent-storage-cas-load.rules
	@rm /lib/udev/rules.d/60-persistent-storage-cas.rules


.PHONY: install uninstall clean distclean
