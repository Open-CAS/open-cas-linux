#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from api.cas import casadm_parser
from api.cas.cache_config import CacheMode
from storage_devices.device import Device
from test_tools import fs_utils


opencas_conf_path = "/etc/opencas/opencas.conf"


class InitConfig:
    def __init__(self):
        self.cache_config_lines = []
        self.core_config_lines = []

    def add_cache(self, cache_id, cache_device: Device,
                  cache_mode: CacheMode = CacheMode.WT, extra_flags=""):
        self.cache_config_lines.append(
            CacheConfigLine(cache_id, cache_device, cache_mode, extra_flags))

    def add_core(self, cache_id, core_id, core_device: Device, extra_flags=""):
        self.core_config_lines.append(CoreConfigLine(cache_id, core_id, core_device, extra_flags))

    def save_config_file(self):
        config_lines = []
        InitConfig.create_default_init_config()
        if self.cache_config_lines:
            config_lines.append(CacheConfigLine.header)
            for c in self.cache_config_lines:
                config_lines.append(str(c))
        if self.core_config_lines:
            config_lines.append(CoreConfigLine.header)
            for c in self.core_config_lines:
                config_lines.append(str(c))
        fs_utils.write_file(opencas_conf_path, '\n'.join(config_lines), False)

    @classmethod
    def create_init_config_from_running_configuration(
            cls, cache_extra_flags="", core_extra_flags=""
    ):
        init_conf = cls()
        for cache in casadm_parser.get_caches():
            init_conf.add_cache(cache.cache_id,
                                cache.cache_device,
                                cache.get_cache_mode(),
                                cache_extra_flags)
            for core in casadm_parser.get_cores(cache.cache_id):
                init_conf.add_core(cache.cache_id, core.core_id, core.core_device, core_extra_flags)
        init_conf.save_config_file()
        return init_conf

    @classmethod
    def create_default_init_config(cls):
        cas_version = casadm_parser.get_casadm_version()
        fs_utils.write_file(opencas_conf_path, f"version={cas_version.base}")


class CacheConfigLine:
    header = "[caches]"

    def __init__(self, cache_id, cache_device: Device,
                 cache_mode: CacheMode, extra_flags=""):
        self.cache_id = cache_id
        self.cache_device = cache_device
        self.cache_mode = cache_mode
        self.extra_flags = extra_flags

    def __str__(self):
        params = [str(self.cache_id), self.cache_device.path,
                  self.cache_mode.name, self.extra_flags]
        return '\t'.join(params)


class CoreConfigLine:
    header = "[cores]"

    def __init__(self, cache_id, core_id, core_device: Device, extra_flags=""):
        self.cache_id = cache_id
        self.core_id = core_id
        self.core_device = core_device
        self.extra_flags = extra_flags

    def __str__(self):
        params = [str(self.cache_id), str(self.core_id),
                  self.core_device.path, self.extra_flags]
        return '\t'.join(params)
