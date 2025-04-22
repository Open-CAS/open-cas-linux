#
# Copyright(c) 2012-2021 Intel Corporation
# Copyright(c) 2021-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#
ifeq ($(M),)

.PHONY: sync distsync

sync:
	@cd $(OCFDIR) && $(MAKE) inc O=$(PWD)
	@cd $(OCFDIR) && $(MAKE) src O=$(PWD)/cas_cache

distsync:
	@cd $(OCFDIR) && $(MAKE) distclean O=$(PWD)
	@cd $(OCFDIR) && $(MAKE) distclean O=$(PWD)/cas_cache

endif
