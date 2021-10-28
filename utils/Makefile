#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

include ../tools/helpers.mk

CASCTL_DIR = /lib/opencas
UDEVRULES_DIR = /lib/udev/rules.d
METADATA_DIR:=$(PWD)/../.metadata
UTILS_DIR:=$(PWD)/../utils
UDEV:=$(shell which udevadm)
SYSTEMCTL := $(shell which systemctl)
PYTHON3 := $(shell which python3)

ifneq "$(wildcard /usr/lib/systemd/system)" ""
	SYSTEMD_DIR=/usr/lib/systemd/system
else
	SYSTEMD_DIR=/lib/systemd/system
endif

# Just a placeholder when running make from parent dir without install/uninstall arg
all: ;

install: install_files
ifeq (, $(PYTHON3))
	$(error package 'python3' not found)
else
	@$(UDEV) control --reload-rules
	@$(SYSTEMCTL) daemon-reload
	@$(SYSTEMCTL) -q enable open-cas-shutdown
	@$(SYSTEMCTL) -q enable open-cas

install_files:
	@echo "Installing Open-CAS utils"

	@install -m 755 -d $(DESTDIR)/etc/opencas
	@install -m 644 $(UTILS_DIR)/opencas.conf $(DESTDIR)/etc/opencas/opencas.conf
	@install -m 444 $(UTILS_DIR)/ioclass-config.csv $(DESTDIR)/etc/opencas/ioclass-config.csv
	@install -m 755 -d $(DESTDIR)/var/lib/opencas
	@install -m 644 $(METADATA_DIR)/cas_version $(DESTDIR)/var/lib/opencas/cas_version
	@mkdir -p $(DESTDIR)/usr/share/man/man5
	@install -m 644 $(UTILS_DIR)/opencas.conf.5 $(DESTDIR)/usr/share/man/man5/opencas.conf.5

	@install -m 755 -d $(DESTDIR)$(CASCTL_DIR)
	@install -m 644 opencas.py $(DESTDIR)$(CASCTL_DIR)/opencas.py
	@install -m 755 casctl $(DESTDIR)$(CASCTL_DIR)/casctl
	@install -m 755 open-cas-loader $(DESTDIR)$(CASCTL_DIR)/open-cas-loader

	@mkdir -p $(DESTDIR)/etc/dracut.conf.d/
	@install -m 644 etc/dracut.conf.d/opencas.conf $(DESTDIR)/etc/dracut.conf.d/opencas.conf

	@mkdir -p $(DESTDIR)/sbin
	@ln -fs $(CASCTL_DIR)/casctl $(DESTDIR)/sbin/casctl

	@mkdir -p $(DESTDIR)$(UDEVRULES_DIR)
	@install -m 644 60-persistent-storage-cas-load.rules $(DESTDIR)$(UDEVRULES_DIR)/60-persistent-storage-cas-load.rules
	@install -m 644 60-persistent-storage-cas.rules $(DESTDIR)$(UDEVRULES_DIR)/60-persistent-storage-cas.rules

	@install -m 755 -d $(DESTDIR)/usr/share/doc/opencas

	@mkdir -p $(DESTDIR)/usr/share/man/man8
	@install -m 644 casctl.8 $(DESTDIR)/usr/share/man/man8/casctl.8

	@mkdir -p $(DESTDIR)$(SYSTEMD_DIR)
	@install -m 644 open-cas-shutdown.service $(DESTDIR)$(SYSTEMD_DIR)/open-cas-shutdown.service
	@install -m 644 open-cas.service $(DESTDIR)$(SYSTEMD_DIR)/open-cas.service
	@install -m 755 -d $(DESTDIR)$(SYSTEMD_DIR)/../system-shutdown
	@install -m 755 open-cas.shutdown $(DESTDIR)$(SYSTEMD_DIR)/../system-shutdown/open-cas.shutdown
endif

uninstall:
	@echo "Uninstalling Open-CAS utils"

	$(call remove-file,$(DESTDIR)/etc/opencas/opencas.conf)
	$(call remove-file,$(DESTDIR)/etc/opencas/ioclass-config.csv)
	$(call remove-directory,$(DESTDIR)/etc/opencas)
	$(call remove-file,$(DESTDIR)/var/lib/opencas/cas_version)
	$(call remove-directory,$(DESTDIR)/var/lib/opencas)
	$(call remove-file,$(DESTDIR)/usr/share/man/man5/opencas.conf.5)

	$(call remove-file,$(DESTDIR)$(CASCTL_DIR)/opencas.py)
	$(call remove-file,$(DESTDIR)$(CASCTL_DIR)/casctl)
	$(call remove-file,$(DESTDIR)$(CASCTL_DIR)/open-cas-loader)
	$(call remove-directory,$(DESTDIR)$(CASCTL_DIR))

	$(call remove-file,$(DESTDIR)/etc/dracut.conf.d/opencas.conf)

	$(call remove-file,$(DESTDIR)/sbin/casctl)

	$(call remove-file,$(DESTDIR)/usr/share/man/man8/casctl.8)

	$(call remove-file,$(DESTDIR)$(UDEVRULES_DIR)/60-persistent-storage-cas-load.rules)
	$(call remove-file,$(DESTDIR)$(UDEVRULES_DIR)/60-persistent-storage-cas.rules)
	@$(UDEV) control --reload-rules

	@$(SYSTEMCTL) -q disable open-cas-shutdown
	@$(SYSTEMCTL) -q disable open-cas
	@$(SYSTEMCTL) daemon-reload

	$(call remove-file,$(DESTDIR)$(SYSTEMD_DIR)/open-cas-shutdown.service)
	$(call remove-file,$(DESTDIR)$(SYSTEMD_DIR)/open-cas.service)
	$(call remove-file,$(DESTDIR)$(SYSTEMD_DIR)/../system-shutdown/open-cas.shutdown)

.PHONY: install uninstall clean distclean
