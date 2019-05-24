#!/bin/bash
#
# Copyright(c) 2012-2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

obj-m += test_mod.o

MAKE_DIR:=$(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))

all:
	make -C /lib/modules/$(shell uname -r)/build M=$(MAKE_DIR) modules
clean:
	make -C /lib/modules/$(shell uname -r)/build M=$(MAKE_DIR) clean
