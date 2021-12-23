#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from core.test_run import TestRun
import json


class Response_structure:
    response_keys = {"opencas.cache.stats.get": ["Cache id", "Cache id", "IO class", "Usage",
                                                 "Requests", "Blocks", "Errors"],
                     "opencas.cache.core.stats.get": ["Cache id", "Cache id", "IO class", "Usage",
                                                      "Requests", "Blocks", "Errors"],
                     "opencas.cache.ioclass.stats.get": ["Cache id", "Cache id", "IO class",
                                                         "Usage", "Requests", "Blocks", "Errors"],
                     "opencas.cache.core.ioclass.stats.get": ["Cache id", "Cache id", "IO class",
                                                          "Usage", "Requests", "Blocks", "Errors"],
                     "opencas.cache_list.get": [],
                     "opencas.cache.info.get": ["Cache id", "Cache device", "Core(s) id(s)",
                                            "Cache details"],
                     "opencas.cache.core.info.get": ["Core id", "Core path", "Core details",
                                                     "State"],
                     "opencas.cache.ioclass.info.get": ["Class id", "IO class details"]}


class Json_api:
    response_structure = Response_structure()

    @classmethod
    def send_request(cls, request: dict):
        request = json.dumps(request)
        TestRun.LOGGER.info(f"Request:  '{request}'")
        exec_json_api_path = "./usr/sbin/opencas-json-api"
        command = f"cd / && echo '{request}' | {exec_json_api_path}"
        response = TestRun.executor.run(command)
        if response.exit_code != 0:
            raise Exception(f"Failed Request: '{request}'")
        return response.stdout

    @classmethod
    def verify_response_structure(cls, command: str, response: str):
        response = json.loads(response)
        for key in cls.response_structure.response_keys[command]:
            if key not in response.keys():
                raise Exception(f"Response structure is not valid: missing {key} field")
        TestRun.LOGGER.info(f"Request: {command} PASSED")
        return True

    @classmethod
    def verify_response_content(cls, response: str):
        raise NotImplementedError()

    @classmethod
    def check_json_api_installed(cls):
        command = "ls /sbin/opencas-json-api"
        output = TestRun.executor.run(command)
        if output.exit_code != 0:
            return True
        return False
