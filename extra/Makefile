#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

DIRS := prometheus

all clean install uninstall:
	@for dir in $(DIRS); do \
		$(MAKE) -C $$dir $@; \
	done

.PHONY: all clean install uninstall
