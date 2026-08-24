#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2025 Huawei Technologies
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#
# If $(M) is defined, we've been invoked from the
# kernel build system and can use its language.
ifneq ($(M),)

include $(M)/config.mk

obj-y += cas_cache/
obj-y += cas_bd/

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

CACHE_MODULE = cas_cache
DISK_MODULE = cas_bd

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

default: sync check_configured_kernel
	cd $(KERNEL_DIR) && $(MAKE) M=$(PWD) modules

# generated_defines.h describes the kernel API './configure' probed. Compiling
# it against another kernel produces code for an API that kernel may not have,
# so say so up front instead of failing with a wall of compiler errors.
check_configured_kernel:
	@configured=$$(sed -n 's/^#define CAS_CONFIGURED_KERNEL_DIR "\(.*\)"$$/\1/p' \
		$(PWD)/generated_defines.h 2>/dev/null); \
	building=$$(realpath $(KERNEL_DIR)); \
	if [ -n "$$configured" ] && [ "$$configured" != "$$building" ]; then \
		echo "ERROR: './configure' was run for the kernel in $$configured," >&2; \
		echo "but the modules are being built against $$building." >&2; \
		echo "Re-run './configure --kernel-dir $$building' first." >&2; \
		exit 1; \
	fi

clean:
	cd $(KERNEL_DIR) && make M=$(PWD) clean
distclean: clean distsync
	@rm -f $(PWD)/generated_defines.h

install: install_files
	@$(DEPMOD)
	@$(MODPROBE) $(CACHE_MODULE) || ( \
		echo "See dmesg for more information" >&2 && \
		rm -f $(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko && exit 1 \
		)


install_files:
	@echo "Installing Open-CAS modules"
	@install -m 644 -D cas_cache/$(CACHE_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko
	@install -m 644 -D cas_bd/$(DISK_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko

uninstall:
	@echo "Uninstalling Open-CAS modules"
	$(call remove-module,$(CACHE_MODULE))
	$(call remove-module,$(DISK_MODULE))

	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko)
	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko)
	$(call remove-directory,$(DESTDIR)$(MODULES_DIR))

	@$(DEPMOD)

reinstall: uninstall install

.PHONY: all default check_configured_kernel clean distclean sync distsync install uninstall

endif
