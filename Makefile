#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

PWD:=$(shell pwd)

default: all

DIRS_NOCAS:=modules utils
DIRS:=casadm $(DIRS_NOCAS)

DEBUG_STATS ?= 0

.PHONY: default all clean distclean $(DIRS)

all $(MAKECMDGOALS): $(DIRS)

$(DIRS_NOCAS):
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

archives:
	@tools/pckgen.sh $(PWD) tar zip

rpm:
	@tools/pckgen.sh $(PWD) rpm --debug

srpm:
	@tools/pckgen.sh $(PWD) srpm

deb:
	@tools/pckgen.sh $(PWD) deb --debug

dsc:
	@tools/pckgen.sh $(PWD) dsc
