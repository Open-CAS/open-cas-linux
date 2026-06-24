#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from api.cas.ioctl.cas_structs import *
from api.cas.ioctl.ioctl import IOWR


class IORequest:
    def __init__(self,
                 command_number: RequestCode,
                 command_direction=None):
        self.command_number = command_number.value
        self.command_struct = self.get_struct()
        self.command = command_direction(self.command_number, self.command_struct)

    def get_struct(self):
        pass


class StartCacheRequest(IORequest):
    def __init__(self,
                 cache_path_name: str,
                 cache_id: int = 1,
                 init_cache: InitCache = InitCache.CACHE_INIT_NEW,
                 caching_mode: CacheMode = CacheMode.default,
                 line_size: CacheLineSize = CacheLineSize.default,
                 force: int = 1):
        self.cache_id = ctypes.c_uint16(cache_id).value
        self.init_cache = init_cache.value
        self.cache_path_name = ctypes.create_string_buffer(
            bytes(cache_path_name, encoding='ascii'), MAX_STR_LEN).value
        self.caching_mode = caching_mode.value
        self.line_size = line_size.value
        self.force = ctypes.c_uint8(force).value
        super().__init__(RequestCode.START_CACHE_CODE, IOWR)

    def get_struct(self):
        return StartCacheStructure(
            cache_id=self.cache_id,
            init_cache=self.init_cache,
            cache_path_name=self.cache_path_name,
            caching_mode=self.caching_mode,
            line_size=self.line_size,
            force=self.force
        )

    def __repr__(self):
        return f'{self.command_struct}'


class StopCacheRequest(IORequest):
    def __init__(self,
                 cache_id: int = 1,
                 flush_data: int = 1):
        self.cache_id = ctypes.c_uint16(cache_id).value
        self.flush_data = ctypes.c_uint8(flush_data).value
        super().__init__(RequestCode.STOP_CACHE_CODE, IOWR)

    def get_struct(self):
        return StopCacheStructure(
            cache_id=self.cache_id,
            flush_data=self.flush_data
        )

    def __repr__(self):
        return f'{self.command_struct}'
