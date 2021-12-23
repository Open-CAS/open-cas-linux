#!/bin/bash
#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

obj-m += test_mod.o

MAKE_DIR:=$(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))

check_cflag=$(shell echo "" | \
	gcc -c -xc ${1} -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

ifeq ($(call check_cflag,-Werror=int-conversion), 1)
EXTRA_CFLAGS += -Werror=int-conversion
endif

all:
	make -C $(KERNEL_DIR) M=$(MAKE_DIR) modules
clean:
	make -C $(KERNEL_DIR) M=$(MAKE_DIR) clean
