#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import csv
import io
import json

from datetime import timedelta, datetime
from typing import List

from api.cas import casadm
from api.cas.cache_config import *
from api.cas.casadm_params import *
from api.cas.ioclass_config import IoClass
from api.cas.version import CasVersion
from core.test_run_utils import TestRun
from storage_devices.device import Device
from test_utils.output import CmdException


class Stats(dict):
    def __str__(self):
        return json.dumps(self, default=lambda o: str(o), indent=2)


def get_filter(filter: List[StatsFilter]):
    """Prepare list of statistic sections which should be retrieved and parsed."""
    if filter is None or StatsFilter.all in filter:
        _filter = [f for f in StatsFilter if (f != StatsFilter.all and f != StatsFilter.conf)]
    else:
        _filter = [f for f in filter if (f != StatsFilter.all and f != StatsFilter.conf)]

    return _filter


def get_caches() -> list:
    from api.cas.cache import Cache

    caches_dict = get_cas_devices_dict()["caches"]
    caches_list = []

    for cache in caches_dict.values():
        caches_list.append(
            Cache(
                device=(Device(cache["device_path"]) if cache["device_path"] != "-" else None),
                cache_id=cache["id"],
            )
        )

    return caches_list


def get_cores(cache_id: int) -> list:
    from api.cas.core import Core, CoreStatus

    cores_dict = get_cas_devices_dict()["cores"].values()

    def is_active(core):
        return CoreStatus[core["status"].lower()] == CoreStatus.active

    return [
        Core(core["device_path"], core["cache_id"])
        for core in cores_dict
        if is_active(core) and core["cache_id"] == cache_id
    ]


def get_inactive_cores(cache_id: int) -> list:
    from api.cas.core import Core, CoreStatus

    cores_dict = get_cas_devices_dict()["cores"].values()

    def is_inactive(core):
        return CoreStatus[core["status"].lower()] == CoreStatus.inactive

    return [
        Core(core["device_path"], core["cache_id"])
        for core in cores_dict
        if is_inactive(core) and core["cache_id"] == cache_id
    ]


def get_detached_cores(cache_id: int) -> list:
    from api.cas.core import Core, CoreStatus

    cores_dict = get_cas_devices_dict()["cores"].values()

    def is_detached(core):
        return CoreStatus[core["status"].lower()] == CoreStatus.detached

    return [
        Core(core["device_path"], core["cache_id"])
        for core in cores_dict
        if is_detached(core) and core["cache_id"] == cache_id
    ]


def get_cas_devices_dict() -> dict:
    device_list = list(csv.DictReader(casadm.list_caches(OutputFormat.csv).stdout.split("\n")))
    devices = {"caches": {}, "cores": {}, "core_pool": {}}
    cache_id = -1
    core_pool = False
    for device in device_list:
        if device["type"] == "cache":
            cache_id = int(device["id"])
            core_pool = False
            params = [
                ("id", cache_id),
                ("device_path", device["disk"]),
                ("status", device["status"]),
            ]
            devices["caches"][cache_id] = dict([(key, value) for key, value in params])

        elif device["type"] == "core":
            params = [
                ("cache_id", cache_id),
                ("device_path", device["disk"]),
                ("status", device["status"]),
            ]
            if core_pool:
                params.append(("core_pool", device))
                devices["core_pool"][device["disk"]] = dict([(key, value) for key, value in params])
            else:
                devices["cores"][(cache_id, int(device["id"]))] = dict(
                    [(key, value) for key, value in params]
                )

        elif device["type"] == "core pool":
            core_pool = True

    return devices


def get_flushing_progress(cache_id: int, core_id: int = None):
    casadm_output = casadm.list_caches(OutputFormat.csv)
    lines = casadm_output.stdout.splitlines()
    for line in lines:
        line_elements = line.split(",")
        if (
            core_id is not None
            and line_elements[0] == "core"
            and int(line_elements[1]) == core_id
            or core_id is None
            and line_elements[0] == "cache"
            and int(line_elements[1]) == cache_id
        ):
            try:
                flush_line_elements = line_elements[3].split()
                flush_percent = flush_line_elements[1][1:]
                return float(flush_percent)
            except Exception:
                break
    raise CmdException(
        f"There is no flushing progress in casadm list output. (cache {cache_id}"
        f"{' core ' + str(core_id) if core_id is not None else ''})",
        casadm_output,
    )


def wait_for_flushing(cache, core, timeout: timedelta = timedelta(seconds=30)):
    start_time = datetime.now()
    while datetime.now() - start_time < timeout:
        try:
            get_flushing_progress(cache.cache_id, core.core_id)
            return
        except CmdException:
            continue
    TestRun.fail("Flush not started!")


def get_flush_parameters_alru(cache_id: int):
    casadm_output = casadm.get_param_cleaning_alru(
        cache_id, casadm.OutputFormat.csv
    ).stdout.splitlines()
    flush_parameters = FlushParametersAlru()
    for line in casadm_output:
        if "max buffers" in line:
            flush_parameters.flush_max_buffers = int(line.split(",")[1])
        if "Activity threshold" in line:
            flush_parameters.activity_threshold = Time(milliseconds=int(line.split(",")[1]))
        if "Stale buffer time" in line:
            flush_parameters.staleness_time = Time(seconds=int(line.split(",")[1]))
        if "Wake up time" in line:
            flush_parameters.wake_up_time = Time(seconds=int(line.split(",")[1]))
    return flush_parameters


def get_flush_parameters_acp(cache_id: int):
    casadm_output = casadm.get_param_cleaning_acp(
        cache_id, casadm.OutputFormat.csv
    ).stdout.splitlines()
    flush_parameters = FlushParametersAcp()
    for line in casadm_output:
        if "max buffers" in line:
            flush_parameters.flush_max_buffers = int(line.split(",")[1])
        if "Wake up time" in line:
            flush_parameters.wake_up_time = Time(milliseconds=int(line.split(",")[1]))
    return flush_parameters


def get_seq_cut_off_parameters(cache_id: int, core_id: int):
    casadm_output = casadm.get_param_cutoff(
        cache_id, core_id, casadm.OutputFormat.csv
    ).stdout.splitlines()
    seq_cut_off_params = SeqCutOffParameters()
    for line in casadm_output:
        if "Sequential cutoff threshold" in line:
            seq_cut_off_params.threshold = Size(int(line.split(",")[1]), Unit.KibiByte)
        if "Sequential cutoff policy" in line:
            seq_cut_off_params.policy = SeqCutOffPolicy.from_name(line.split(",")[1])
        if "Sequential cutoff promotion request count threshold" in line:
            seq_cut_off_params.promotion_count = int(line.split(",")[1])
    return seq_cut_off_params


def get_casadm_version():
    casadm_output = casadm.print_version(OutputFormat.csv).stdout.split("\n")
    version_str = casadm_output[1].split(",")[-1]
    return CasVersion.from_version_string(version_str)


def get_io_class_list(cache_id: int) -> list:
    ret = []
    casadm_output = casadm.list_io_classes(cache_id, OutputFormat.csv).stdout.splitlines()
    casadm_output.pop(0)  # Remove header
    for line in casadm_output:
        values = line.split(",")
        ioclass = IoClass(int(values[0]), values[1], int(values[2]), values[3])
        ret.append(ioclass)
    return ret


def get_core_info_for_cache_by_path(core_disk_path: str, target_cache_id: int) -> dict | None:
    output = casadm.list_caches(OutputFormat.csv, by_id_path=True)
    reader = csv.DictReader(io.StringIO(output.stdout))
    cache_id = -1
    for row in reader:
        if row["type"] == "cache":
            cache_id = int(row["id"])
        if row["type"] == "core" and row["disk"] == core_disk_path and target_cache_id == cache_id:
            return {
                "core_id": row["id"],
                "core_device": row["disk"],
                "status": row["status"],
                "exp_obj": row["device"],
            }

    return None
