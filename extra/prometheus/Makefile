#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

LIBOPENCAS_DIR := $(CURDIR)/../../libopencas

all: opencas_exporter

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

install: all
	install -m 755 -D opencas_exporter $(DESTDIR)/usr/bin/opencas_exporter
	install -m 644 -D opencas_exporter.service $(DESTDIR)$(SYSTEMD_DIR)/opencas_exporter.service
	$(SYSTEMCTL) daemon-reload

uninstall:
	-$(SYSTEMCTL) disable --now opencas_exporter
	rm -f $(DESTDIR)/usr/bin/opencas_exporter
	rm -f $(DESTDIR)$(SYSTEMD_DIR)/opencas_exporter.service
	$(SYSTEMCTL) daemon-reload

clean:
	rm -f opencas_exporter
	$(MAKE) -C $(LIBOPENCAS_DIR) clean

.PHONY: all install uninstall clean
