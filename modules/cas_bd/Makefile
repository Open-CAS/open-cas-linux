#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

include $(M)/config.mk

obj-m := cas_bd.o

cas_bd-c    = $(shell find $(M)/cas_bd -name \*.c)
cas_bd-objs = $(patsubst $(M)/cas_bd/%.c,%.o,$(cas_bd-c))
