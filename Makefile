#
# Copyright(c) 2012-2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

default: all

DIRS:=modules casadm utils

.PHONY: default all clean distclean $(DIRS)

all $(MAKECMDGOALS): $(DIRS)

$(DIRS):
	cd $@ && $(MAKE) $(MAKECMDGOALS)
