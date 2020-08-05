#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
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
                  cache_mode: CacheMode = CacheMode.WT, load=None, extra_flags=""):
        self.cache_config_lines.append(
            CacheConfigLine(cache_id, cache_device, cache_mode, load, extra_flags))

    def add_core(self, cache_id, core_id, core_device: Device):
        self.core_config_lines.append(CoreConfigLine(cache_id, core_id, core_device))

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
    def create_init_config_from_running_configuration(cls, load: bool = None, extra_flags=""):
        init_conf = cls()
        for cache in casadm_parser.get_caches():
            init_conf.add_cache(cache.cache_id,
                                cache.cache_device,
                                cache.get_cache_mode(),
                                load,
                                extra_flags)
            for core in casadm_parser.get_cores(cache.cache_id):
                init_conf.add_core(cache.cache_id, core.core_id, core.core_device)
        init_conf.save_config_file()
        return init_conf

    @classmethod
    def create_default_init_config(cls):
        cas_version = casadm_parser.get_casadm_version()
        fs_utils.write_file(opencas_conf_path, f"version={cas_version.base}")


class CacheConfigLine:
    header = "[caches]"

    def __init__(self, cache_id, cache_device: Device,
                 cache_mode: CacheMode, load=None, extra_flags=""):
        self.cache_id = cache_id
        self.cache_device = cache_device
        self.load = load
        self.cache_mode = cache_mode
        self.extra_flags = extra_flags

    def __str__(self):
        cache_symlink = self.cache_device.get_device_link("/dev/disk/by-id")
        cache_device_path = cache_symlink.full_path if cache_symlink is not None \
            else self.cache_device.system_path
        params = [str(self.cache_id), cache_device_path]
        if self.load is not None:
            params.append("yes" if self.load else "no")
        params.append(self.cache_mode.name)
        params.append(self.extra_flags)
        return '\t'.join(params)


class CoreConfigLine:
    header = "[cores]"

    def __init__(self, cache_id, core_id, core_device: Device):
        self.cache_id = cache_id
        self.core_id = core_id
        self.core_device = core_device

    def __str__(self):
        core_symlink = self.core_device.get_device_link("/dev/disk/by-id")
        core_device_path = core_symlink.full_path if core_symlink is not None \
            else self.core_device.system_path
        params = [str(self.cache_id), str(self.core_id), core_device_path]
        return '\t'.join(params)
