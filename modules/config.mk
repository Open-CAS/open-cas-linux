#
# Copyright(c) 2012-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

VERSION_FILE := $(M)/../.metadata/cas_version

check_cflag=$(shell echo "" | \
	gcc -c -xc ${1} -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

-include $(VERSION_FILE)
ccflags-y += -DCAS_VERSION_MAIN=$(CAS_VERSION_MAIN)
ccflags-y += -DCAS_VERSION_MAJOR=$(CAS_VERSION_MAJOR)
ccflags-y += -DCAS_VERSION_MINOR=$(CAS_VERSION_MINOR)
ccflags-y += -DCAS_VERSION=\"$(CAS_VERSION)\"
ccflags-y += -Ofast -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security
ccflags-y += -I$(M)
ccflags-y += -I$(M)/cas_cache
ccflags-y += -I$(M)/include
ccflags-y += -DCAS_KERNEL=\"$(KERNELRELEASE)\"

check_header=$(shell echo "\#include <${1}>" | \
	gcc -c -xc -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

INCDIR = $(PWD)/include

KERNEL_VERSION = $(shell echo $(KERNELRELEASE) | cut -d'.' -f1)
KERNEL_MAJOR = $(shell echo $(KERNELRELEASE) | cut -d'.' -f2)

ccflags-y += -Werror

ldflags-y += -z noexecstack -z relro -z now

# workaround for missing objtool in kernel devel package
ifeq ($(shell expr $(KERNEL_VERSION) == 4 \& $(KERNEL_MAJOR) == 14),1)
ifeq ($(CONFIG_STACK_VALIDATION), y)
OBJTOOL=$(shell [ -f tools/objtool/objtool ] && echo "y")
ifneq ($(OBJTOOL), y)
CONFIG_STACK_VALIDATION=
endif
endif
endif

-include $(M)/extra.mk
