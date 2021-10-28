#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
include $(M)/config.mk

obj-m := cas_cache.o

cas_cache-c    = $(shell find $(M)/cas_cache -name \*.c)
cas_cache-objs = $(patsubst $(M)/cas_cache/%.c,%.o,$(cas_cache-c))
