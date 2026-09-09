#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

-include ../../.metadata/cas_config

LIBOPENCAS_DIR := $(CURDIR)/../../libopencas

# The exporter uses netlink interface. Build it only if netlink is enabled.
ifeq ($(WITH_NETLINK),1)
EXPORTER := opencas_exporter
endif

all: $(EXPORTER)

$(LIBOPENCAS_DIR)/libopencas.a:
	$(MAKE) -C $(LIBOPENCAS_DIR)

opencas_exporter: $(LIBOPENCAS_DIR)/libopencas.a
	go build -o $@ .

SYSTEMCTL := $(shell which systemctl)

ifneq "$(wildcard /usr/lib/systemd/system)" ""
	SYSTEMD_DIR=/usr/lib/systemd/system
else
	SYSTEMD_DIR=/lib/systemd/system
endif

install: install_files
ifdef EXPORTER
	$(SYSTEMCTL) daemon-reload
endif

install_files: all
ifdef EXPORTER
	install -m 755 -D opencas_exporter $(DESTDIR)/usr/bin/opencas_exporter
	install -m 644 -D opencas_exporter.service $(DESTDIR)$(SYSTEMD_DIR)/opencas_exporter.service
endif

uninstall:
	-$(SYSTEMCTL) disable --now opencas_exporter
	rm -f $(DESTDIR)/usr/bin/opencas_exporter
	rm -f $(DESTDIR)$(SYSTEMD_DIR)/opencas_exporter.service
	$(SYSTEMCTL) daemon-reload

clean:
	rm -f opencas_exporter
	$(MAKE) -C $(LIBOPENCAS_DIR) clean

distclean: clean

.PHONY: all install install_files uninstall clean distclean
