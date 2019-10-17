#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from api.cas import casadm_parser
from api.cas.cache_config import CacheMode
from storage_devices.device import Device
from test_tools import fs_utils


opencas_conf_path = "/etc/opencas/opencas.conf"


def create_init_config_from_running_configuration(load: bool = None, extra_flags=""):
    cache_lines = []
    core_lines = []
    for cache in casadm_parser.get_caches():
        cache_lines.append(CacheConfigLine(cache.cache_id,
                                           cache.cache_device,
                                           cache.get_cache_mode(),
                                           load,
                                           extra_flags))
        for core in casadm_parser.get_cores(cache.cache_id):
            core_lines.append(CoreConfigLine(cache.cache_id,
                                             core.core_id,
                                             core.core_device))
    config_lines = []
    create_default_init_config()
    if len(cache_lines) > 0:
        config_lines.append(CacheConfigLine.header)
        for c in cache_lines:
            config_lines.append(str(c))
    if len(core_lines) > 0:
        config_lines.append(CoreConfigLine.header)
        for c in core_lines:
            config_lines.append(str(c))
    fs_utils.write_file(opencas_conf_path, '\n'.join(config_lines), False)


def create_default_init_config():
    cas_version = casadm_parser.get_casadm_version()
    fs_utils.write_file(opencas_conf_path,
                        f"version={'.'.join(str(x) for x in cas_version.release[0:3])}")


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
