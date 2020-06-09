#
# Copyright(c) 2012-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

VERSION_FILE := $(M)/../.metadata/cas_version

check_cflag=$(shell echo "" | \
	gcc -c -xc ${1} -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

-include $(VERSION_FILE)
EXTRA_CFLAGS += -DCAS_VERSION_MAIN=$(CAS_VERSION_MAIN)
EXTRA_CFLAGS += -DCAS_VERSION_MAJOR=$(CAS_VERSION_MAJOR)
EXTRA_CFLAGS += -DCAS_VERSION_MINOR=$(CAS_VERSION_MINOR)
EXTRA_CFLAGS += -DCAS_VERSION=\"$(CAS_VERSION)\"
EXTRA_CFLAGS += -O2 -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security

EXTRA_CFLAGS += -I$(M)
EXTRA_CFLAGS += -I$(M)/cas_cache
EXTRA_CFLAGS += -I$(M)/include
EXTRA_CFLAGS += -DCAS_KERNEL=\"$(KERNELRELEASE)\"

check_header=$(shell echo "\#include <${1}>" | \
	gcc -c -xc -o /dev/null - 2>/dev/null; \
	if [ $$? -eq 0 ]; then echo 1; else echo 0; fi; )

INCDIR = $(PWD)/include

NVME_FULL = 0

SLES ?= $(shell cat /etc/SuSE-release 2>/dev/null)
ifneq ($(SLES),)
EXTRA_CFLAGS += -DCAS_UAPI_LINUX_NVME_IOCTL
EXTRA_CFLAGS += -DCAS_NVME_PARTIAL
EXTRA_CFLAGS += -DCAS_SLES
SLES_VERSION := $(shell cat /etc/os-release |\
       sed -n 's/VERSION="\([0-9]\+\)-\(.\+\)"/\1\2/p')
EXTRA_CFLAGS += -DCAS_SLES$(SLES_VERSION)
INCDIR = ""
endif

ifeq ($(call check_header,$(INCDIR)/uapi/nvme.h), 1)
EXTRA_CFLAGS += -DCAS_UAPI_NVME_IOCTL
EXTRA_CFLAGS += -DCAS_UAPI_NVME
EXTRA_CFLAGS += -DCAS_NVME_PARTIAL
endif

ifeq ($(call check_header,$(INCDIR)/uapi/linux/nvme.h), 1)
EXTRA_CFLAGS += -DCAS_UAPI_LINUX_NVME
EXTRA_CFLAGS += -DCAS_NVME_PARTIAL
endif

ifeq ($(call check_header,$(INCDIR)/uapi/linux/nvme_ioctl.h), 1)
EXTRA_CFLAGS += -DCAS_UAPI_LINUX_NVME_IOCTL
EXTRA_CFLAGS += -DCAS_NVME_PARTIAL
ifeq ($(shell cat /etc/redhat-release 2>/dev/null | grep "\(Red Hat\|CentOS\) [a-zA-Z ]* 7\.[45]" | wc -l), 1)
NVME_FULL = 1
endif
endif

KERNEL_VERSION = $(shell echo $(KERNELRELEASE) | cut -d'.' -f1)
KERNEL_MAJOR = $(shell echo $(KERNELRELEASE) | cut -d'.' -f2)

ifeq ($(shell expr $(KERNEL_VERSION) \>= 4 \& $(KERNEL_MAJOR) \> 11),1)
NVME_FULL = 0
endif

ifeq ($(NVME_FULL),1)
EXTRA_CFLAGS += -DCAS_NVME_FULL
endif

EXTRA_CFLAGS += -Werror

EXTRA_LDFLAGS += -z noexecstack -z relro -z now

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
