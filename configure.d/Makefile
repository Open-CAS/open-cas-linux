#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#


obj-m += test_mod.o

MAKE_DIR:=$(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))

check_cflag=$(shell echo "" | \
	gcc -c -xc ${1} -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

ifeq ($(call check_cflag,-Werror=int-conversion), 1)
ccflags-y += -Werror=int-conversion
endif
KBUILD_CFLAGS += -Wno-error
all:
	make -C $(KERNEL_DIR) M=$(MAKE_DIR) modules
clean:
	make -C $(KERNEL_DIR) M=$(MAKE_DIR) clean
