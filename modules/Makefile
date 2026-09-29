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
ifneq ($(FALLBACK_BUILD),1)
obj-y += cas_bd/
endif

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
DISK_SYMVERS = $(DISK_MODULE).symvers

# In-flight upgrade support. When FALLBACK_SYMVERS points at the symvers
# of the loaded cas_bd, a second cas_cache.ko is built against it. 'make
# upgrade' installs it under FALLBACK_INSTALL_DIR (outside /lib/modules/, so
# depmod ignores it) next to a copy of the loaded cas_bd, and loads it in
# place of the old cas_cache; after reboot the new cas_bd + cas_cache from
# the standard location take over.
FALLBACK_BUILD_DIR = $(PWD)/.fallback
FALLBACK_CACHE_KO = $(FALLBACK_BUILD_DIR)/cas_cache/$(CACHE_MODULE).ko
FALLBACK_BASE_SYMVERS = $(FALLBACK_BUILD_DIR)/$(DISK_SYMVERS)
FALLBACK_INSTALL_DIR ?= /lib/opencas/fallback/$(KERNEL_VERSION)

# Directory holding the files of the loaded cas_bd: the standard location,
# or the fallback one if an upgrade was not followed by reboot
LOADED_DISK_DIR = $(shell loaded=$$(cat /sys/module/$(DISK_MODULE)/srcversion 2>/dev/null); \
	for dir in $(MODULES_DIR) $(FALLBACK_INSTALL_DIR); do \
		if [ -n "$$loaded" ] && [ -f $$dir/$(DISK_SYMVERS) ] && \
				[ "$$(modinfo -F srcversion $$dir/$(DISK_MODULE).ko 2>/dev/null)" = "$$loaded" ]; then \
			echo $$dir; break; \
		fi; \
	done)

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
ifneq ($(FALLBACK_SYMVERS),)
	@test -f $(FALLBACK_SYMVERS) || { \
		echo "ERROR: FALLBACK_SYMVERS=$(FALLBACK_SYMVERS) not found" >&2; \
		exit 1; \
	}
	@echo "=== Building fallback $(CACHE_MODULE) against $(FALLBACK_SYMVERS) ==="
	@rm -rf $(FALLBACK_BUILD_DIR)
	@mkdir -p $(FALLBACK_BUILD_DIR)
	@find $(PWD) -mindepth 1 -maxdepth 1 ! -name .fallback \
		-exec cp -a {} $(FALLBACK_BUILD_DIR)/ \;
	@cd $(KERNEL_DIR) && $(MAKE) M=$(FALLBACK_BUILD_DIR) FALLBACK_BUILD=1 clean
	cd $(KERNEL_DIR) && $(MAKE) M=$(FALLBACK_BUILD_DIR) FALLBACK_BUILD=1 \
		METADATA_DIR=$(PWD)/../.metadata \
		KBUILD_EXTRA_SYMBOLS=$(FALLBACK_SYMVERS) modules
	@cp $(FALLBACK_SYMVERS) $(FALLBACK_BASE_SYMVERS)
endif

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
	@rm -rf $(FALLBACK_BUILD_DIR)
distclean: clean distsync
	@rm -f $(PWD)/generated_defines.h
	@rm -f $(PWD)/$(DISK_SYMVERS)

install: install_files
	@$(DEPMOD)
	@$(MODPROBE) $(CACHE_MODULE) || { \
		echo "See dmesg for more information" >&2; exit 1; \
	}


install_files:
	@echo "Installing Open-CAS modules"
	@install -m 644 -D cas_cache/$(CACHE_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko
	@install -m 644 -D cas_bd/$(DISK_MODULE).ko $(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko
	@grep 'cas_bd/$(DISK_MODULE)' Module.symvers > $(PWD)/$(DISK_SYMVERS)
	@install -m 644 -D $(PWD)/$(DISK_SYMVERS) $(DESTDIR)$(MODULES_DIR)/$(DISK_SYMVERS)

uninstall:
	@echo "Unloading Open-CAS modules"
	$(call remove-module,$(CACHE_MODULE))
	$(call remove-module,$(DISK_MODULE))
	@$(MAKE) uninstall_files

uninstall_files:
	@echo "Uninstalling Open-CAS modules"
	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(CACHE_MODULE).ko)
	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(DISK_MODULE).ko)
	$(call remove-file,$(DESTDIR)$(MODULES_DIR)/$(DISK_SYMVERS))
	$(call remove-directory,$(DESTDIR)$(MODULES_DIR))

	@rm -rf $(DESTDIR)$(FALLBACK_INSTALL_DIR)

	@$(DEPMOD)

reinstall: uninstall install

# Steps of the in-flight upgrade, driven by 'make upgrade' in the top
# directory, which also passes UPGRADE_DIR to keep the preserved files in
upgrade_check:
	@test -f $(FALLBACK_CACHE_KO) || { \
		echo "ERROR: Fallback $(CACHE_MODULE).ko not built, rebuild with" \
			"FALLBACK_SYMVERS=<symvers of the loaded $(DISK_MODULE)>" >&2; \
		exit 1; \
	}
	@test -n "$(LOADED_DISK_DIR)" || { \
		echo "ERROR: $(DISK_MODULE) not loaded or its installed files" \
			"do not match the loaded module" >&2; \
		exit 1; \
	}
	@cmp -s $(FALLBACK_BASE_SYMVERS) $(LOADED_DISK_DIR)/$(DISK_SYMVERS) || { \
		echo "ERROR: Fallback $(CACHE_MODULE).ko was not built against" \
			"the loaded $(DISK_MODULE), rebuild with" \
			"FALLBACK_SYMVERS=$(LOADED_DISK_DIR)/$(DISK_SYMVERS)" >&2; \
		exit 1; \
	}

upgrade_unload:
	@echo "Unloading $(CACHE_MODULE) module"
	@$(RMMOD) $(CACHE_MODULE)

upgrade_preserve:
	@echo "Preserving loaded $(DISK_MODULE)"
	@install -m 644 -D $(LOADED_DISK_DIR)/$(DISK_MODULE).ko $(UPGRADE_DIR)/$(DISK_MODULE).ko
	@install -m 644 -D $(LOADED_DISK_DIR)/$(DISK_SYMVERS) $(UPGRADE_DIR)/$(DISK_SYMVERS)

upgrade_load:
	@$(DEPMOD)
	@echo "Installing fallback $(CACHE_MODULE) to $(FALLBACK_INSTALL_DIR)"
	@install -m 644 -D $(UPGRADE_DIR)/$(DISK_MODULE).ko $(FALLBACK_INSTALL_DIR)/$(DISK_MODULE).ko
	@install -m 644 -D $(UPGRADE_DIR)/$(DISK_SYMVERS) $(FALLBACK_INSTALL_DIR)/$(DISK_SYMVERS)
	@install -m 644 -D $(FALLBACK_CACHE_KO) $(FALLBACK_INSTALL_DIR)/$(CACHE_MODULE).ko
	@insmod $(FALLBACK_INSTALL_DIR)/$(CACHE_MODULE).ko || { \
		echo "See dmesg for more information" >&2; exit 1; \
	}

.PHONY: all default check_configured_kernel clean distclean sync distsync install install_files \
	uninstall uninstall_files upgrade_check upgrade_unload upgrade_preserve upgrade_load

endif
