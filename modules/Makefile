#
# Copyright(c) 2012-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# If $(M) is defined, we've been invoked from the
# kernel build system and can use its language.
ifneq ($(M),)

include $(M)/config.mk

obj-y += cas_cache/
obj-y += cas_disk/

# Otherwise we were called directly from the command
# line; invoke the kernel build system.
else

include ../tools/helpers.mk

define remove-module
	@if (lsmod | grep -q ${1}); then rmmod ${1}; \
	else echo "WARNING: Module ${1} is not loaded"; fi
endef

OCFDIR=$(PWD)/../ocf
PWD=$(shell pwd)
KERNEL_VERSION ?= "$(shell uname -r)"
KERNEL_DIR ?= "/lib/modules/$(KERNEL_VERSION)/build"
MODULES_DIR=/lib/modules/$(KERNEL_VERSION)/extra/block/opencas

DISK_MODULE = cas_disk
CACHE_MODULE = cas_cache

DEPMOD:=$(shell which depmod)
RMMOD :=$(shell which rmmod)
MODPROBE:=$(shell which modprobe)

all: default

# Extra targets and file configuration
ifneq ($(wildcard $(PWD)/extra.mk),)
include $(PWD)/extra.mk
else
sync distsync:
endif

default: sync
	cd $(KERNEL_DIR) && $(MAKE) M=$(PWD) modules

clean:
	cd $(KERNEL_DIR) && make M=$(PWD) clean
distclean: clean distsync
	@rm -f $(PWD)/generated_defines.h

install: install_files
	@$(DEPMOD)
	@$(MODPROBE) $(CACHE_MODULE)

install_files:
	@echo "Installing Open-CAS modules"
	@install -m 644 -D cas_disk/$(DISK_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko
	@install -m 644 -D cas_cache/$(CACHE_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko

uninstall:
	@echo "Uninstalling Open-CAS modules"
	$(call remove-module,$(CACHE_MODULE))
	$(call remove-module,$(DISK_MODULE))

	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko)
	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko)
	$(call remove-directory,$(DESTDIR)$(MODULES_DIR))

	@$(DEPMOD)

reinstall: uninstall install

.PHONY: all default clean distclean sync distsync install uninstall

endif
