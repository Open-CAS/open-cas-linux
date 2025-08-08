#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies
# Copyright(c) 2025 Brian J. Murrell
# SPDX-License-Identifier: BSD-3-Clause
#

PWD:=$(shell pwd)

default: all

DIRS:=modules casadm utils

.PHONY: default all clean distclean $(DIRS)

all $(MAKECMDGOALS): $(DIRS)

$(DIRS):
ifneq ($(MAKECMDGOALS),archives)
ifneq ($(MAKECMDGOALS),rpm)
ifneq ($(MAKECMDGOALS),srpm)
ifneq ($(MAKECMDGOALS),deb)
ifneq ($(MAKECMDGOALS),dsc)
	cd $@ && $(MAKE) $(MAKECMDGOALS)
casadm: modules
	cd $@ && $(MAKE) $(MAKECMDGOALS)
endif
endif
endif
endif
endif

ifneq ($(KERNEL_VERSION),)
BUILD_ARGS=--kernel_version $(KERNEL_VERSION)
endif

ifneq ($(MOCK_ROOT),)
ifeq ($(KERNEL_VERSION),)
$(error KERNEL_VERSION must be set when using MOCK_ROOT)
endif
BUILD_ARGS=--mock_root $(MOCK_ROOT) --kernel_version $(KERNEL_VERSION)
endif

archives:
	@tools/pckgen.sh $(PWD) tar zip

rpm:
	@tools/pckgen.sh $(PWD) rpm --debug $(BUILD_ARGS)

srpm:
	@tools/pckgen.sh $(PWD) srpm

deb:
	@tools/pckgen.sh $(PWD) deb --debug

dsc:
	@tools/pckgen.sh $(PWD) dsc
