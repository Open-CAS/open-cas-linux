#
# Copyright(c) 2012-2022 Intel Corporation
# Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

include ../tools/helpers.mk
-include ./flags.mk

PWD:=$(shell pwd)
MODULESDIR:=$(PWD)/../modules
METADATA_DIR:=$(PWD)/../.metadata
BINARY_PATH = /sbin

VERSION_FILE := $(METADATA_DIR)/cas_version

#
# Section below enables creating build with experimental features
#
ifeq ($(CAS_EXT_EXP),1)
DEFINES    = WI_AVAILABLE
endif

#
# Add defines for version
#
-include $(VERSION_FILE)
DEFINES   += CAS_VERSION_MAIN=$(CAS_VERSION_MAIN)
DEFINES   += CAS_VERSION_MAJOR=$(CAS_VERSION_MAJOR)
DEFINES   += CAS_VERSION_MINOR=$(CAS_VERSION_MINOR)
DEFINES   += CAS_VERSION=\"$(CAS_VERSION)\"
ifeq ($(DEBUG_STATS),1)
DEFINES   += OCF_CONFIG_DEBUG_STATS
endif

#
# Include directories
#
INCLUDES     = .
INCLUDES    += $(MODULESDIR)/include

OBJDIR       = .obj/
TARGET	     = casadm
TARGETS      = $(TARGET)

#
# Source to be complied
#

OBJS  = cas_lib.o
OBJS += cas_main.o
OBJS += argp.o
OBJS += statistics_view_csv.o
OBJS += cas_lib_utils.o
OBJS += statistics_model.o
OBJS += table.o
OBJS += psort.o
OBJS += statistics_view_text.o
OBJS += intvector.o
OBJS += statistics_view.o
OBJS += statistics_view_raw_csv.o
OBJS += csvparse.o
OBJS += extended_err_msg.o
OBJS += safeclib/memmove_s.o
OBJS += safeclib/memcpy_s.o
OBJS += safeclib/memset_s.o
OBJS += safeclib/strncpy_s.o
OBJS += safeclib/strcmp_s.o
OBJS += safeclib/strtok_s.o
OBJS += safeclib/safe_str_constraint.o
OBJS += safeclib/ignore_handler_s.o
OBJS += safeclib/safe_mem_constraint.o
OBJS += safeclib/mem_primitives_lib.o
OBJS += safeclib/strcat_s.o
OBJS += safeclib/strcmpfld_s.o
OBJS += safeclib/strcpy_s.o
OBJS += safeclib/strcpyfld_s.o
OBJS += safeclib/strcpyfldin_s.o
OBJS += safeclib/strcpyfldout_s.o
OBJS += safeclib/strcspn_s.o
OBJS += safeclib/strfirstchar_s.o
OBJS += safeclib/strfirstdiff_s.o
OBJS += safeclib/strfirstsame_s.o
OBJS += safeclib/strisalphanumeric_s.o
OBJS += safeclib/strisascii_s.o
OBJS += safeclib/strisdigit_s.o
OBJS += safeclib/strishex_s.o
OBJS += safeclib/strislowercase_s.o
OBJS += safeclib/strismixedcase_s.o
OBJS += safeclib/strispassword_s.o
OBJS += safeclib/strisuppercase_s.o
OBJS += safeclib/strlastchar_s.o
OBJS += safeclib/strlastdiff_s.o
OBJS += safeclib/strlastsame_s.o
OBJS += safeclib/strljustify_s.o
OBJS += safeclib/strncat_s.o
OBJS += safeclib/strnlen_s.o
OBJS += safeclib/strnterminate_s.o
OBJS += safeclib/strpbrk_s.o
OBJS += safeclib/strprefix_s.o
OBJS += safeclib/strremovews_s.o
OBJS += safeclib/strspn_s.o
OBJS += safeclib/strstr_s.o
OBJS += safeclib/strzero_s.o

#
# Flags for C compilation
#
CFLAGS     = $(patsubst %,-I%,$(INCLUDES))
CFLAGS    += $(patsubst %,-D%,$(DEFINES))
ifdef DEBUG
CFLAGS    += -O0 -g
else
CFLAGS    += -O2 -D_FORTIFY_SOURCE=2
endif
ifdef DEBUG_PACKAGE
CFLAGS    += -g3
endif
CFLAGS    += -Wall -Werror -z relro -z now -fstack-protector -fPIC -Wformat -Wformat-security -fno-strict-aliasing

#
# Flags for linking
#
LDFLAGS    = -z noexecstack -z relro -z now -pie -pthread -lm
#
# Targets
#

all: sync
	$(MAKE) build

build: $(TARGETS)

sync:
	@cd $(MODULESDIR) && $(MAKE) sync

#
# Include dependencies file
#
$(TARGET): $(TARGET).a
	@echo "  LD " $@
	@$(CC) $(CFLAGS) -o $(TARGET) $< $(LDFLAGS)

$(TARGET).a: $(patsubst %,$(OBJDIR)%,$(OBJS))
	@echo "  AR " $@
	@ar rcs $@ $^
	@echo "  AR " libcas.a
	@cp -f $@ libcas.a
	@ar d libcas.a $(OBJDIR)argp.o $(OBJDIR)cas_main.c

#
# Generic target for C file
#
$(OBJDIR)%.o: %.c Makefile
	@echo "  CC " $<
	@mkdir -p $(dir $@)
ifeq ($(strip $(CAS_VERSION_MAIN)),)
	$(error "No version file")
endif
	@$(CC) -c $(CFLAGS) -MMD -o "$@" "$<"

-include $(addprefix $(OBJDIR),$(OBJS:.o=.d))

clean:
	@echo "  CLEAN "
	@rm -f *.a $(TARGETS)
	@rm -f $(shell find -name \*.d) $(shell find -name \*.o)

distclean: clean
	@rm -f $(PWD)/generated_defines.h
	@rm -f $(PWD)/flags.mk

install: install_files

install_files:
	@echo "Installing casadm"
	@install -m 755 -D $(TARGET) $(DESTDIR)$(BINARY_PATH)/$(TARGET)
	@install -m 644 -D $(TARGET).8 $(DESTDIR)/usr/share/man/man8/$(TARGET).8

uninstall:
	@echo "Uninstalling casadm"
	$(call remove-file,$(DESTDIR)$(BINARY_PATH)/$(TARGET))
	$(call remove-file,$(DESTDIR)/usr/share/man/man8/$(TARGET).8)

.PHONY: clean distclean all sync build install uninstall
