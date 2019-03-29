#
# Copyright(c) 2012-2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
# If KERNELRELEASE is defined, we've been invoked from the
# kernel build system and can use its language.
ifneq ($(KERNELRELEASE),)

include $(M)/config.mk

obj-y += cas_cache/
obj-y += cas_disk/

# Otherwise we were called directly from the command
# line; invoke the kernel build system.
else

VERSION_FILE=$(PWD)/CAS_VERSION

OCFDIR=$(PWD)/../ocf
KERNEL_DIR ?= "/lib/modules/$(shell uname -r)/build"
PWD=$(shell pwd)
KERNEL_VERSION := $(shell uname -r)
MODULES_DIR=/lib/modules/$(KERNEL_VERSION)/extra

DISK_MODULE = cas_disk
CACHE_MODULE = cas_cache

DEPMOD:=$(shell which depmod)
RMMOD :=$(shell which rmmod)
MODPROBE:=$(shell which modprobe)

all: default

$(VERSION_FILE):
	./CAS_VERSION_GEN

# Extra targets and file configuration
ifneq ($(wildcard $(PWD)/extra.mk),)
include $(PWD)/extra.mk
else
sync distsync:
endif

default: $(VERSION_FILE) sync
	cd $(KERNEL_DIR) && $(MAKE) M=$(PWD) modules

clean:
	cd $(KERNEL_DIR) && make M=$(PWD) clean

distclean: clean distsync

install:
	@echo "Installing Open-CAS modules"
	@install -m 755 -d $(MODULES_DIR)
	@install -m 744 cas_disk/$(DISK_MODULE).ko $(MODULES_DIR)/$(DISK_MODULE).ko
	@install -m 744 cas_cache/$(CACHE_MODULE).ko $(MODULES_DIR)/$(CACHE_MODULE).ko

	@$(DEPMOD)
	@$(MODPROBE) $(CACHE_MODULE)

uninstall:
	@echo "Uninstalling Open-CAS modules"
	@$(RMMOD) $(CACHE_MODULE)
	@$(RMMOD) $(DISK_MODULE)

	@rm $(MODULES_DIR)/$(CACHE_MODULE).ko
	@rm $(MODULES_DIR)/$(DISK_MODULE).ko

	@$(DEPMOD)

reinstall: uninstall install

.PHONY: all default clean distclean sync distsync install uninstall

endif
