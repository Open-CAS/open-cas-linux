#
# Copyright(c) 2012-2022 Intel Corporation
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
endif
endif
endif
endif
endif

archives:
	@tools/pckgen $(PWD) tar zip

rpm:
	@tools/pckgen $(PWD) rpm --debug

srpm:
	@tools/pckgen $(PWD) srpm --debug

deb:
	@tools/pckgen $(PWD) deb

dsc:
	@tools/pckgen $(PWD) dsc
