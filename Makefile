#
# Copyright(c) 2012-2019 Intel Corporation
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
	cd $@ && $(MAKE) $(MAKECMDGOALS)
endif
endif
endif

archives:
	@utils/pckgen $(PWD) tar zip

rpm:
	@utils/pckgen $(PWD) rpm

srpm:
	@utils/pckgen $(PWD) srpm
