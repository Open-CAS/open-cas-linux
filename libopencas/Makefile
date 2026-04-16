#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

MODULES_DIR := $(CURDIR)/../modules/include

CFLAGS += -I$(MODULES_DIR) -fPIC -Wall -Wextra -O2

all: libopencas.a

libopencas.a: libopencas.o
	$(AR) rcs $@ $^

libopencas.o: libopencas.c libopencas.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o *.a

.PHONY: all clean
