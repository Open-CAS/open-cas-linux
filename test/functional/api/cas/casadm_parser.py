#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
import csv

import json
import re
from api.cas import casadm
from test_utils.output import CmdException
from test_utils.size import parse_unit
from storage_devices.device import Device
from api.cas.cache_config import *
from api.cas.casadm_params import *
from api.cas.version import CasVersion
from datetime import timedelta
from typing import List

from api.cas import casadm
from api.cas.cache_config import *
from api.cas.casadm_params import *
from test_utils.size import parse_unit


class Stats(dict):
    def __str__(self):
        return json.dumps(self, default=lambda o: str(o), indent=2)


def parse_stats_unit(unit: str):
    if unit is None:
        return ""

    unit = re.search(r".*[^\]]", unit).group()

    if unit == "s":
        return "s"
    elif unit == "%":
        return "%"
    elif unit == "Requests":
        return "requests"
    else:
        return parse_unit(unit)


def get_filter(filter: List[StatsFilter]):
    """Prepare list of statistic sections which should be retrieved and parsed. """
    if filter is None or StatsFilter.all in filter:
        _filter = [
            f for f in StatsFilter if (f != StatsFilter.all and f != StatsFilter.conf)
        ]
    else:
        _filter = [
            f for f in filter if (f != StatsFilter.all and f != StatsFilter.conf)
        ]

    return _filter


def get_statistics(
    cache_id: int,
    core_id: int = None,
    io_class_id: int = None,
    filter: List[StatsFilter] = None,
    percentage_val: bool = False,
):
    stats = Stats()

    _filter = get_filter(filter)

    per_io_class = True if io_class_id is not None else False

    # No need to retrieve all stats if user specified only 'conf' flag
    if filter != [StatsFilter.conf]:
        csv_stats = casadm.print_statistics(
            cache_id=cache_id,
            core_id=core_id,
            per_io_class=per_io_class,
            io_class_id=io_class_id,
            filter=_filter,
            output_format=casadm.OutputFormat.csv,
        ).stdout.splitlines()

    if filter is None or StatsFilter.conf in filter or StatsFilter.all in filter:
        # Conf statistics have different unit or may have no unit at all. For parsing
        # convenience they are gathered separately. As this is only configuration stats
        # there is no risk they are divergent.
        conf_stats = casadm.print_statistics(
            cache_id=cache_id,
            core_id=core_id,
            per_io_class=per_io_class,
            io_class_id=io_class_id,
            filter=[StatsFilter.conf],
            output_format=casadm.OutputFormat.csv,
        ).stdout.splitlines()
        stat_keys = conf_stats[0]
        stat_values = conf_stats[1]
        for (name, val) in zip(stat_keys.split(","), stat_values.split(",")):
            # Some of configuration stats have no unit
            try:
                stat_name, stat_unit = name.split(" [")
            except ValueError:
                stat_name = name
                stat_unit = None

            stat_name = stat_name.lower()

            # 'dirty for' and 'cache size' stats occurs twice
            if stat_name in stats:
                continue

            stat_unit = parse_stats_unit(stat_unit)

            if isinstance(stat_unit, Unit):
                stats[stat_name] = Size(float(val), stat_unit)
            elif stat_unit == "s":
                stats[stat_name] = timedelta(seconds=int(val))
            elif stat_unit == "":
                # Some of stats without unit can be a number like IDs,
                # some of them can be string like device path
                try:
                    stats[stat_name] = float(val)
                except ValueError:
                    stats[stat_name] = val

    # No need to parse all stats if user specified only 'conf' flag
    if filter == [StatsFilter.conf]:
        return stats

    stat_keys = csv_stats[0]
    stat_values = csv_stats[1]
    for (name, val) in zip(stat_keys.split(","), stat_values.split(",")):
        if percentage_val and " [%]" in name:
            stats[name.split(" [")[0].lower()] = float(val)
        elif not percentage_val and "[%]" not in name:
            stat_name, stat_unit = name.split(" [")

            stat_unit = parse_stats_unit(stat_unit)

            stat_name = stat_name.lower()

            if isinstance(stat_unit, Unit):
                stats[stat_name] = Size(float(val), stat_unit)
            elif stat_unit == "requests":
                stats[stat_name] = float(val)
            else:
                raise ValueError(f"Invalid unit {stat_unit}")

    return stats


def get_caches():  # This method does not return inactive or detached CAS devices
    from api.cas.cache import Cache
    caches_list = []
    lines = casadm.list_caches(OutputFormat.csv).stdout.split('\n')
    for line in lines:
        args = line.split(',')
        if args[0] == "cache":
            current_cache = Cache(Device(args[2]))
            caches_list.append(current_cache)
    return caches_list


def get_cores(cache_id: int):
    from api.cas.core import Core, CoreStatus
    cores_list = []
    lines = casadm.list_caches(OutputFormat.csv).stdout.split('\n')
    is_proper_core_line = False
    for line in lines:
        args = line.split(',')
        if args[0] == "core" and is_proper_core_line:
            core_status_str = args[3].lower()
            is_valid_status = CoreStatus[core_status_str].value[0] <= 1
            if is_valid_status:
                cores_list.append(Core(args[2], cache_id))
        if args[0] == "cache":
            is_proper_core_line = True if int(args[1]) == cache_id else False
    return cores_list


def get_cas_devices_dict():
    device_list = list(csv.DictReader(casadm.list_caches(OutputFormat.csv).stdout.split('\n')))
    devices = {"core_pool": [], "caches": {}, "cores": {}}
    core_pool = False
    prev_cache_id = -1

    for device in device_list:
        if device["type"] == "core pool":
            core_pool = True
            continue

        if device["type"] == "cache":
            core_pool = False
            prev_cache_id = int(device["id"])
            devices["caches"].update(
                {
                    int(device["id"]): {
                        "device": device["disk"],
                        "status": device["status"],
                    }
                }
            )
        elif device["type"] == "core":
            core = {"device": device["disk"], "status": device["status"]}
            if core_pool:
                devices["core_pool"].append(core)
            else:
                core.update({"cache_id": prev_cache_id})
                devices["cores"].update(
                    {(prev_cache_id, int(device["id"])): core}
                )
    return devices


def get_flushing_progress(cache_id: int, core_id: int = None):
    casadm_output = casadm.list_caches(OutputFormat.csv).stdout.splitlines()
    for line in casadm_output:
        line_elements = line.split(',')
        if core_id is not None and line_elements[0] == "core" \
                and int(line_elements[1]) == core_id \
                or core_id is None and line_elements[0] == "cache" \
                and int(line_elements[1]) == cache_id:
            try:
                flush_line_elements = line_elements[3].split()
                flush_percent = flush_line_elements[1][1:]
                return float(flush_percent)
            except Exception:
                break
    raise CmdException(f"There is no flushing progress in casadm list output. (cache {cache_id}"
                       f"{' core ' + str(core_id) if core_id is not None else ''})",
                       casadm_output)


def get_flush_parameters_alru(cache_id: int):
    casadm_output = casadm.get_param_cleaning_alru(cache_id,
                                                   casadm.OutputFormat.csv).stdout.splitlines()
    flush_parameters = FlushParametersAlru()
    for line in casadm_output:
        if 'max buffers' in line:
            flush_parameters.flush_max_buffers = int(line.split(',')[1])
        if 'Activity threshold' in line:
            flush_parameters.activity_threshold = Time(milliseconds=int(line.split(',')[1]))
        if 'Stale buffer time' in line:
            flush_parameters.staleness_time = Time(seconds=int(line.split(',')[1]))
        if 'Wake up time' in line:
            flush_parameters.wake_up_time = Time(seconds=int(line.split(',')[1]))
    return flush_parameters


def get_flush_parameters_acp(cache_id: int):
    casadm_output = casadm.get_param_cleaning_acp(cache_id,
                                                  casadm.OutputFormat.csv).stdout.splitlines()
    flush_parameters = FlushParametersAcp()
    for line in casadm_output:
        if 'max buffers' in line:
            flush_parameters.flush_max_buffers = int(line.split(',')[1])
        if 'Wake up time' in line:
            flush_parameters.wake_up_time = Time(milliseconds=int(line.split(',')[1]))
    return flush_parameters


def get_seq_cut_off_parameters(cache_id: int, core_id: int):
    casadm_output = casadm.get_param_cutoff(
        cache_id, core_id, casadm.OutputFormat.csv).stdout.splitlines()
    seq_cut_off_params = SeqCutOffParameters()
    for line in casadm_output:
        if 'threshold' in line:
            seq_cut_off_params.threshold = Size(int(line.split(',')[1]), Unit.KibiByte)
        if 'policy' in line:
            seq_cut_off_params.policy = SeqCutOffPolicy.from_name(line.split(',')[1])
    return seq_cut_off_params


def get_casadm_version():
    casadm_output = casadm.print_version(OutputFormat.csv).stdout.split('\n')
    version_str = casadm_output[1].split(',')[-1]
    return CasVersion.from_version_string(version_str)
