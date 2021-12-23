#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

define remove-file
	@if [ -f ${1} ] || [ -L ${1} ]; then rm -rf ${1}; \
	else echo "WARNING: Cannot find file ${1}"; fi
endef

define remove-directory
	@if [ -d ${1} ]; then rm -rf ${1}; \
	else echo "WARNING: Cannot find directory ${1}"; fi
endef

