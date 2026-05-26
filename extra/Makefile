#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

DIRS := prometheus

all clean distclean install install_files uninstall:
	@for dir in $(DIRS); do \
		$(MAKE) -C $$dir $@; \
	done

.PHONY: all clean distclean install uninstall
