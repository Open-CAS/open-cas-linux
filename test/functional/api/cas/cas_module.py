#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from aenum import Enum

from test_utils import os_utils
from test_utils.os_utils import ModuleRemoveMethod


class CasModule(Enum):
    cache = "cas_cache"
    disk = "cas_disk"


def reload_all_cas_modules():
    os_utils.unload_kernel_module(CasModule.cache.value, ModuleRemoveMethod.modprobe)
    os_utils.load_kernel_module(CasModule.cache.value)


def unload_all_cas_modules():
    os_utils.unload_kernel_module(CasModule.cache.value,
                                  os_utils.ModuleRemoveMethod.rmmod)
    os_utils.unload_kernel_module(CasModule.disk.value,
                                  os_utils.ModuleRemoveMethod.rmmod)
