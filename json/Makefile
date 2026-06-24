#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

include ../tools/helpers.mk

BINARY_PATH = /sbin

all:
	@mkdir -p bin
	@go build -o bin/opencas-json-api main.go
install:		
	@echo " Installing JSON API "
	@install -m 755 bin/opencas-json-api $(DESTDIR)/sbin/opencas-json-api 

uninstall:
	@echo " Uninstalling JSON API "    
	@$(call remove-file,$(DESTDIR)/sbin/opencas-json-api)

clean:
	@rm -f bin/opencas-json-api

.PHONY: all clean install uninstall
