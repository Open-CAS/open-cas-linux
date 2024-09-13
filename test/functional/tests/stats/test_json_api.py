#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest

from api.cas import casadm
from api.cas.json_api import Json_api
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_utils.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_json_api_requests():
    with TestRun.step("Prepare CAS device."):
        cache_disk = TestRun.disks['cache']
        cache_disk.create_partitions([Size(20, Unit.GibiByte)])
        cache_dev = cache_disk.partitions[0]

        core_disk = TestRun.disks['core']
        core_disk.create_partitions([Size(20, Unit.GibiByte)])
        core_dev = core_disk.partitions[0]

        cache = casadm.start_cache(cache_dev, force=True)
        core = cache.add_core(core_dev)
        TestRun.LOGGER.info(TestRun.executor.run("casadm -L").stdout)

    with TestRun.step("Parametrize Request valid"):
        io_class = 0
        cache_id = cache.cache_id
        core_id = core.core_id

    with TestRun.step("Corner values"):
        io_class = 0
        cache_id_min = 1
        core_id_max = 0
        cache_id_max = 4096
        core_id_max = 16384

    with TestRun.step("Init all requests"):
        request_opencas_cache_stats_get = {"command": "opencas.cache.stats.get",
                                           "params": {"cache id": cache_id}}
        request_opencas_cache_core_stats_get = {"command": "opencas.cache.stats.get",
                                                "params": {"cache id": cache_id, "core id":
                                                    core_id}}
        request_opencas_cache_ioclass_stats_get = {"command": "opencas.cache.stats.get",
                                                   "params": {"cache id": cache_id,
                                                              "io class": io_class}}
        request_opencas_cache_core_ioclass_stats_get = {"command": "opencas.cache.stats.get",
                                                        "params": {"cache id": cache_id, "core id":
                                                            core_id, "io class": io_class}}
        request_opencas_cache_list_get = {"command": "opencas.cache_list.get",
                                          "params": {}}
        request_opencas_cache_info_get = {"command": "opencas.cache.info.get",
                                          "params": {"cache id": cache_id, }}
        request_opencas_core_info_get = {"command": "opencas.cache.core.info.get",
                                         "params": {"cache id": cache_id, "core id": core_id}}
        request_opencas_ioclass_info_get = {"command": "opencas.cache.ioclass.info.get",
                                            "params": {"cache id": cache_id, "io class": io_class}}

    with TestRun.group("JSON API requests"):
        with TestRun.step("GET CACHE REQUEST"):
            response = Json_api.send_request(request_opencas_cache_stats_get)
            Json_api.verify_response_structure(request_opencas_cache_stats_get["command"], response)
        with TestRun.step("GET CACHE CORE REQUEST"):
            response = Json_api.send_request(request_opencas_cache_core_stats_get)
            Json_api.verify_response_structure(
                request_opencas_cache_core_stats_get["command"], response)
        with TestRun.step("GET CACHE IO CLASS REQUEST"):
            response = Json_api.send_request(request_opencas_cache_ioclass_stats_get)
            Json_api.verify_response_structure(
                request_opencas_cache_ioclass_stats_get["command"], response)
        with TestRun.step("GET CACHE CORE IO CLAS REQUEST"):
            response = Json_api.send_request(request_opencas_cache_core_ioclass_stats_get)
            Json_api.verify_response_structure(
                request_opencas_cache_core_ioclass_stats_get["command"], response)
        with TestRun.step("GET CACHE LIST"):
            response = Json_api.send_request(request_opencas_cache_list_get)
            Json_api.verify_response_structure(request_opencas_cache_list_get["command"], response)
        with TestRun.step("GET CACHE INFO"):
            response = Json_api.send_request(request_opencas_cache_info_get)
            Json_api.verify_response_structure(request_opencas_cache_info_get["command"], response)
        with TestRun.step("GET CORE INFO"):
            response = Json_api.send_request(request_opencas_core_info_get)
            Json_api.verify_response_structure(request_opencas_core_info_get["command"], response)
        with TestRun.step("GET IO CLASS INFO"):
            response = Json_api.send_request(request_opencas_ioclass_info_get)
            Json_api.verify_response_structure(
                request_opencas_ioclass_info_get["command"], response)

    with TestRun.group("JSON API invalid requests"):
        pass
