#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
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
	@utils/pckgen $(PWD) tar zip

rpm:
	@utils/pckgen $(PWD) rpm --debug

srpm:
	@utils/pckgen $(PWD) srpm --debug

deb:
	@utils/pckgen $(PWD) deb

dsc:
	@utils/pckgen $(PWD) dsc
