#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

PWD:=$(shell pwd)

default: all

DIRS:=modules casadm utils extra

.PHONY: default all clean distclean $(DIRS)

all $(MAKECMDGOALS): $(DIRS)

$(DIRS):
ifneq ($(MAKECMDGOALS),archives)
ifneq ($(MAKECMDGOALS),rpm)
ifneq ($(MAKECMDGOALS),rpm-dkms)
ifneq ($(MAKECMDGOALS),srpm)
ifneq ($(MAKECMDGOALS),deb)
ifneq ($(MAKECMDGOALS),dsc)
ifneq ($(MAKECMDGOALS),upgrade)
	cd $@ && $(MAKE) $(MAKECMDGOALS)
casadm: modules
	cd $@ && $(MAKE) $(MAKECMDGOALS)
endif
endif
endif
endif
endif
endif
endif

archives:
	@tools/pckgen.sh $(PWD) tar zip

rpm:
	@tools/pckgen.sh $(PWD) rpm --debug

rpm-dkms:
	@tools/pckgen.sh $(PWD) rpm --debug --with-dkms

srpm:
	@tools/pckgen.sh $(PWD) srpm

deb:
	@tools/pckgen.sh $(PWD) deb --debug

dsc:
	@tools/pckgen.sh $(PWD) dsc

# In-flight upgrade: replace the installed release with this one and swap
# the running cas_cache for the fallback one built against the loaded cas_bd.
# The new cas_bd is loaded after reboot.
UPGRADE_DIR = $(PWD)/.upgrade

upgrade:
	@cd modules && $(MAKE) upgrade_check
	@trap 'udevadm control --start-exec-queue' EXIT; \
	trap 'exit 1' INT TERM HUP; \
	set -e; \
	udevadm control --stop-exec-queue; \
	(cd modules && $(MAKE) upgrade_unload); \
	rm -rf $(UPGRADE_DIR); \
	(cd modules && $(MAKE) upgrade_preserve UPGRADE_DIR=$(UPGRADE_DIR)); \
	(cd utils && $(MAKE) upgrade_preserve UPGRADE_DIR=$(UPGRADE_DIR)); \
	(cd modules && $(MAKE) uninstall_files); \
	for dir in casadm utils extra; do (cd $$dir && $(MAKE) uninstall); done; \
	(cd modules && $(MAKE) install_files); \
	for dir in casadm utils extra; do (cd $$dir && $(MAKE) install); done; \
	(cd utils && $(MAKE) upgrade_restore UPGRADE_DIR=$(UPGRADE_DIR)); \
	(cd modules && $(MAKE) upgrade_load UPGRADE_DIR=$(UPGRADE_DIR)); \
	rm -rf $(UPGRADE_DIR)
