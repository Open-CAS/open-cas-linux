#
# Copyright(c) 2019-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import csv

from datetime import timedelta
from enum import Enum
from typing import List
from api.cas import casadm
from api.cas.casadm_params import StatsFilter
from type_def.size import Size, Unit


class UnitType(Enum):
    requests = "[Requests]"
    percentage = "[%]"
    block_4k = "[4KiB Blocks]"
    mebibyte = "[MiB]"
    kibibyte = "[KiB]"
    gibibyte = "[GiB]"
    seconds = "[s]"
    byte = "[B]"

    def __str__(self):
        return self.value


class OperationType(Enum):
    read = "Read"
    write = "Write"

    def __str__(self):
        return self.value


class CacheStats:
    def __init__(
        self,
        cache_id: int,
        filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ):
        stats_dict = get_stats_dict(filter=filter, cache_id=cache_id)

        for section in _get_section_filters(filter):
            match section:
                case StatsFilter.conf:
                    self.config_stats = CacheConfigStats(stats_dict)
                case StatsFilter.usage:
                    self.usage_stats = UsageStats(stats_dict, percentage_val)
                case StatsFilter.req:
                    self.request_stats = RequestStats(stats_dict, percentage_val)
                case StatsFilter.blk:
                    self.block_stats = BlockStats(stats_dict, percentage_val)
                case StatsFilter.err:
                    self.error_stats = ErrorStats(stats_dict, percentage_val)

    def __str__(self):
        # stats_list contains all Class.__str__ methods initialized in CacheStats
        stats_list = [str(getattr(self, stats_item)) for stats_item in self.__dict__]
        return "\n".join(stats_list)

    def __eq__(self, other):
        # check if all initialized variable in self(CacheStats) match other(CacheStats)
        return [getattr(self, stats_item) for stats_item in self.__dict__] == [
            getattr(other, stats_item) for stats_item in other.__dict__
        ]

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.usage_stats -= other.usage_stats
        self.request_stats -= other.request_stats
        self.block_stats -= other.block_stats
        self.error_stats -= other.error_stats
        return self


class CoreStats:
    def __init__(
        self,
        cache_id: int,
        core_id: int,
        filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ):
        stats_dict = get_stats_dict(filter=filter, cache_id=cache_id, core_id=core_id)

        for section in _get_section_filters(filter):
            match section:
                case StatsFilter.conf:
                    self.config_stats = CoreConfigStats(stats_dict)
                case StatsFilter.usage:
                    self.usage_stats = UsageStats(stats_dict, percentage_val)
                case StatsFilter.req:
                    self.request_stats = RequestStats(stats_dict, percentage_val)
                case StatsFilter.blk:
                    self.block_stats = BlockStats(stats_dict, percentage_val)
                case StatsFilter.err:
                    self.error_stats = ErrorStats(stats_dict, percentage_val)

    def __sub__(self, other):
        self.usage_stats -= other.usage_stats
        self.request_stats -= other.request_stats
        self.block_stats -= other.block_stats
        self.error_stats -= other.error_stats
        return self

    def __str__(self):
        # stats_list contains all Class.__str__ methods initialized in CacheStats
        stats_list = [str(getattr(self, stats_item)) for stats_item in self.__dict__]
        return "\n".join(stats_list)

    def __eq__(self, other):
        # check if all initialized variable in self(CacheStats) match other(CacheStats)
        return [getattr(self, stats_item) for stats_item in self.__dict__] == [
            getattr(other, stats_item) for stats_item in other.__dict__
        ]

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])


class CoreIoClassStats:
    def __init__(
        self,
        cache_id: int,
        io_class_id: int,
        core_id: int = None,
        filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ):
        stats_dict = get_stats_dict(
            filter=filter, cache_id=cache_id, core_id=core_id, io_class_id=io_class_id
        )

        for section in _get_section_filters(filter):
            match section:
                case StatsFilter.conf:
                    self.config_stats = IoClassConfigStats(stats_dict)
                case StatsFilter.usage:
                    self.usage_stats = IoClassUsageStats(stats_dict, percentage_val)
                case StatsFilter.req:
                    self.request_stats = RequestStats(stats_dict, percentage_val)
                case StatsFilter.blk:
                    self.block_stats = BlockStats(stats_dict, percentage_val)

    def __eq__(self, other):
        # check if all initialized variable in self(CacheStats) match other(CacheStats)
        return [getattr(self, stats_item) for stats_item in self.__dict__] == [
            getattr(other, stats_item) for stats_item in other.__dict__
        ]

    def __str__(self):
        # stats_list contains all Class.__str__ methods initialized in CacheStats
        stats_list = [str(getattr(self, stats_item)) for stats_item in self.__dict__]
        return "\n".join(stats_list)

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.usage_stats -= other.usage_stats
        self.request_stats -= other.request_stats
        self.block_stats -= other.block_stats


class CacheIoClassStats(CoreIoClassStats):
    def __init__(
        self,
        cache_id: int,
        io_class_id: int,
        filter: List[StatsFilter] = None,
        percentage_val: bool = False,
    ):
        super().__init__(
            cache_id=cache_id,
            io_class_id=io_class_id,
            core_id=None,
            filter=filter,
            percentage_val=percentage_val,
        )


class CacheConfigStats:
    def __init__(self, stats_dict):
        self.cache_id = int(stats_dict["Cache Id"])
        self.cache_size = parse_value(
            value=stats_dict["Cache Size [4KiB Blocks]"], unit_type=UnitType.block_4k
        )
        self.cache_dev = stats_dict["Cache Device"]
        self.exp_obj = stats_dict["Exported Object"]
        self.core_dev = int(stats_dict["Core Devices"])
        self.inactive_core_devices = int(stats_dict["Inactive Core Devices"])
        self.write_policy = stats_dict["Write Policy"]
        self.cleaning_policy = stats_dict["Cleaning Policy"]
        self.promotion_policy = stats_dict["Promotion Policy"]
        self.cache_line_size = parse_value(
            value=stats_dict["Cache line size [KiB]"], unit_type=UnitType.kibibyte
        )
        footprint_prefix = "Metadata Memory Footprint "
        footprint_key = next(k for k in stats_dict if k.startswith(footprint_prefix))
        self.metadata_memory_footprint = parse_value(
            value=stats_dict[footprint_key],
            unit_type=UnitType(footprint_key[len(footprint_prefix) :]),
        )
        self.dirty_for = parse_value(value=stats_dict["Dirty for [s]"], unit_type=UnitType.seconds)
        self.status = stats_dict["Status"]

    def __str__(self):
        return (
            f"Config stats:\n"
            f"Cache ID: {self.cache_id}\n"
            f"Cache size: {self.cache_size}\n"
            f"Cache device: {self.cache_dev}\n"
            f"Exported object: {self.exp_obj}\n"
            f"Core devices: {self.core_dev}\n"
            f"Inactive Core Devices: {self.inactive_core_devices}\n"
            f"Write Policy: {self.write_policy}\n"
            f"Cleaning Policy: {self.cleaning_policy}\n"
            f"Promotion Policy: {self.promotion_policy}\n"
            f"Cache line size: {self.cache_line_size}\n"
            f"Metadata memory footprint: {self.metadata_memory_footprint}\n"
            f"Dirty for: {self.dirty_for}\n"
            f"Status: {self.status}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.cache_id == other.cache_id
            and self.cache_size == other.cache_size
            and self.cache_dev == other.cache_dev
            and self.exp_obj == other.exp_obj
            and self.core_dev == other.core_dev
            and self.inactive_core_devices == other.inactive_core_devices
            and self.write_policy == other.write_policy
            and self.cleaning_policy == other.cleaning_policy
            and self.promotion_policy == other.promotion_policy
            and self.cache_line_size == other.cache_line_size
            and self.metadata_memory_footprint == other.metadata_memory_footprint
            and self.dirty_for == other.dirty_for
            and self.status == other.status
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])


class CoreConfigStats:
    def __init__(self, stats_dict):
        self.core_id = stats_dict["Core Id"]
        self.core_dev = stats_dict["Core Device"]
        self.exp_obj = stats_dict["Exported Object"]
        self.core_size = parse_value(
            value=stats_dict["Core Size [4KiB Blocks]"], unit_type=UnitType.block_4k
        )
        self.dirty_for = parse_value(value=stats_dict["Dirty for [s]"], unit_type=UnitType.seconds)
        self.status = stats_dict["Status"]
        self.seq_cutoff_threshold = parse_value(
            value=stats_dict["Seq cutoff threshold [KiB]"], unit_type=UnitType.kibibyte
        )
        self.seq_cutoff_policy = stats_dict["Seq cutoff policy"]

    def __str__(self):
        return (
            f"Config stats:\n"
            f"Core ID: {self.core_id}\n"
            f"Core device: {self.core_dev}\n"
            f"Exported object: {self.exp_obj}\n"
            f"Core size: {self.core_size}\n"
            f"Dirty for: {self.dirty_for}\n"
            f"Status: {self.status}\n"
            f"Seq cutoff threshold: {self.seq_cutoff_threshold}\n"
            f"Seq cutoff policy: {self.seq_cutoff_policy}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.core_id == other.core_id
            and self.core_dev == other.core_dev
            and self.exp_obj == other.exp_obj
            and self.core_size == other.core_size
            and self.dirty_for == other.dirty_for
            and self.status == other.status
            and self.seq_cutoff_threshold == other.seq_cutoff_threshold
            and self.seq_cutoff_policy == other.seq_cutoff_policy
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])


class IoClassConfigStats:
    def __init__(self, stats_dict):
        self.io_class_id = stats_dict["IO class ID"]
        self.io_class_name = stats_dict["IO class name"]
        self.eviction_priority = stats_dict["Eviction priority"]
        self.max_size = stats_dict["Max size"]

    def __str__(self):
        return (
            f"Config stats:\n"
            f"IO class ID: {self.io_class_id}\n"
            f"IO class name: {self.io_class_name}\n"
            f"Eviction priority: {self.eviction_priority}\n"
            f"Max size: {self.max_size}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.io_class_id == other.io_class_id
            and self.io_class_name == other.io_class_name
            and self.eviction_priority == other.eviction_priority
            and self.max_size == other.max_size
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])


class UsageStats:
    def __init__(self, stats_dict, percentage_val):
        unit = UnitType.percentage if percentage_val else UnitType.block_4k
        self.occupancy = parse_value(value=stats_dict[f"Occupancy {unit}"], unit_type=unit)
        self.free = parse_value(value=stats_dict[f"Free {unit}"], unit_type=unit)
        self.clean = parse_value(value=stats_dict[f"Clean {unit}"], unit_type=unit)
        self.dirty = parse_value(value=stats_dict[f"Dirty {unit}"], unit_type=unit)
        if f"Inactive Occupancy {unit}" in stats_dict:
            self.inactive_occupancy = parse_value(
                value=stats_dict[f"Inactive Occupancy {unit}"], unit_type=unit
            )
        if f"Inactive Clean {unit}" in stats_dict:
            self.inactive_clean = parse_value(
                value=stats_dict[f"Inactive Clean {unit}"], unit_type=unit
            )
        if f"Inactive Dirty {unit}" in stats_dict:
            self.inactive_dirty = parse_value(
                value=stats_dict[f"Inactive Dirty {unit}"], unit_type=unit
            )

    def __str__(self):
        return (
            f"Usage stats:\n"
            f"Occupancy: {self.occupancy}\n"
            f"Free: {self.free}\n"
            f"Clean: {self.clean}\n"
            f"Dirty: {self.dirty}\n"
        )

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.occupancy == other.occupancy
            and self.free == other.free
            and self.clean == other.clean
            and self.dirty == other.dirty
        )

    def __ne__(self, other):
        return not self == other

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.occupancy -= other.occupancy
        self.free -= other.free
        self.clean -= other.clean
        self.dirty -= other.dirty
        return self


class IoClassUsageStats:
    def __init__(self, stats_dict, percentage_val):
        unit = UnitType.percentage if percentage_val else UnitType.block_4k
        self.occupancy = parse_value(value=stats_dict[f"Occupancy {unit}"], unit_type=unit)
        self.clean = parse_value(value=stats_dict[f"Clean {unit}"], unit_type=unit)
        self.dirty = parse_value(value=stats_dict[f"Dirty {unit}"], unit_type=unit)

    def __str__(self):
        return (
            f"Usage stats:\n"
            f"Occupancy: {self.occupancy}\n"
            f"Clean: {self.clean}\n"
            f"Dirty: {self.dirty}\n"
        )

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.occupancy == other.occupancy
            and self.clean == other.clean
            and self.dirty == other.dirty
        )

    def __ne__(self, other):
        return not self == other

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.occupancy -= other.occupancy
        self.clean -= other.clean
        self.dirty -= other.dirty
        return self


class RequestStats:
    def __init__(self, stats_dict, percentage_val):
        unit = UnitType.percentage if percentage_val else UnitType.requests
        self.read = RequestStatsChunk(
            stats_dict=stats_dict, percentage_val=percentage_val, operation=OperationType.read
        )
        self.write = RequestStatsChunk(
            stats_dict=stats_dict, percentage_val=percentage_val, operation=OperationType.write
        )
        self.pass_through_reads = parse_value(
            value=stats_dict[f"Pass-Through reads {unit}"], unit_type=unit
        )
        self.pass_through_writes = parse_value(
            value=stats_dict[f"Pass-Through writes {unit}"], unit_type=unit
        )
        self.requests_serviced = parse_value(
            value=stats_dict[f"Serviced requests {unit}"], unit_type=unit
        )
        self.requests_total = parse_value(
            value=stats_dict[f"Total requests {unit}"], unit_type=unit
        )

    def __str__(self):
        return (
            f"Request stats:\n"
            f"Read:\n{self.read}"
            f"Write:\n{self.write}"
            f"Pass-through reads: {self.pass_through_reads}\n"
            f"Pass-through writes: {self.pass_through_writes}\n"
            f"Serviced requests: {self.requests_serviced}\n"
            f"Total requests: {self.requests_total}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.read == other.read
            and self.write == other.write
            and self.pass_through_reads == other.pass_through_reads
            and self.pass_through_writes == other.pass_through_writes
            and self.requests_serviced == other.requests_serviced
            and self.requests_total == other.requests_total
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.read -= other.read
        self.write -= other.write
        self.pass_through_reads -= other.pass_through_reads
        self.pass_through_writes -= other.pass_through_writes
        self.requests_serviced -= other.requests_serviced
        self.requests_total -= other.requests_total
        return self


class RequestStatsChunk:
    def __init__(self, stats_dict, percentage_val: bool, operation: OperationType):
        unit = UnitType.percentage if percentage_val else UnitType.requests
        self.hits = parse_value(value=stats_dict[f"{operation} hits {unit}"], unit_type=unit)
        self.part_misses = parse_value(
            value=stats_dict[f"{operation} partial misses {unit}"], unit_type=unit
        )
        self.full_misses = parse_value(
            value=stats_dict[f"{operation} full misses {unit}"], unit_type=unit
        )
        self.total = parse_value(value=stats_dict[f"{operation} total {unit}"], unit_type=unit)

    def __str__(self):
        return (
            f"Hits: {self.hits}\n"
            f"Partial misses: {self.part_misses}\n"
            f"Full misses: {self.full_misses}\n"
            f"Total: {self.total}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.hits == other.hits
            and self.part_misses == other.part_misses
            and self.full_misses == other.full_misses
            and self.total == other.total
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.hits -= other.hits
        self.part_misses -= other.part_misses
        self.full_misses -= other.full_misses
        self.total -= other.total
        return self


class BlockStats:
    def __init__(self, stats_dict, percentage_val):
        self.core = BasicStatsChunk(
            stats_dict=stats_dict, percentage_val=percentage_val, device="core"
        )
        self.cache = BasicStatsChunk(
            stats_dict=stats_dict, percentage_val=percentage_val, device="cache"
        )
        self.exp_obj = BasicStatsChunk(
            stats_dict=stats_dict,
            percentage_val=percentage_val,
            device="exported object",
        )

    def __str__(self):
        return (
            f"Block stats:\n"
            f"Core(s):\n{self.core}"
            f"Cache:\n{self.cache}"
            f"Exported object(s):\n{self.exp_obj}"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.core == other.core and self.cache == other.cache and self.exp_obj == other.exp_obj
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.core -= other.core
        self.cache -= other.cache
        self.exp_obj -= other.exp_obj
        return self


class ErrorStats:
    def __init__(self, stats_dict, percentage_val):
        unit = UnitType.percentage if percentage_val else UnitType.requests
        self.cache = BasicStatsChunkError(
            stats_dict=stats_dict, percentage_val=percentage_val, device="Cache"
        )
        self.core = BasicStatsChunkError(
            stats_dict=stats_dict, percentage_val=percentage_val, device="Core"
        )
        self.total_errors = parse_value(value=stats_dict[f"Total errors {unit}"], unit_type=unit)

    def __str__(self):
        return (
            f"Error stats:\n"
            f"Cache errors:\n{self.cache}"
            f"Core errors:\n{self.core}"
            f"Total errors: {self.total_errors}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.cache == other.cache
            and self.core == other.core
            and self.total_errors == other.total_errors
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.cache -= other.cache
        self.core -= other.core
        self.total_errors -= other.total_errors
        return self


class BasicStatsChunk:
    def __init__(self, stats_dict: dict, percentage_val: bool, device: str):
        unit = UnitType.percentage if percentage_val else UnitType.block_4k
        self.reads = parse_value(value=stats_dict[f"Reads from {device} {unit}"], unit_type=unit)
        self.writes = parse_value(value=stats_dict[f"Writes to {device} {unit}"], unit_type=unit)
        self.total = parse_value(value=stats_dict[f"Total to/from {device} {unit}"], unit_type=unit)

    def __str__(self):
        return f"Reads: {self.reads}\nWrites: {self.writes}\nTotal: {self.total}\n"

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.reads == other.reads and self.writes == other.writes and self.total == other.total
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.reads -= other.reads
        self.writes -= other.writes
        self.total -= other.total
        return self


class BasicStatsChunkError:
    def __init__(self, stats_dict: dict, percentage_val: bool, device: str):
        unit = UnitType.percentage if percentage_val else UnitType.requests
        self.reads = parse_value(value=stats_dict[f"{device} read errors {unit}"], unit_type=unit)
        self.writes = parse_value(value=stats_dict[f"{device} write errors {unit}"], unit_type=unit)
        self.total = parse_value(value=stats_dict[f"{device} total errors {unit}"], unit_type=unit)

    def __str__(self):
        return f"Reads: {self.reads}\nWrites: {self.writes}\nTotal: {self.total}\n"

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.reads == other.reads and self.writes == other.writes and self.total == other.total
        )

    def __iter__(self):
        return iter([getattr(self, stats_item) for stats_item in self.__dict__])

    def __sub__(self, other):
        self.reads -= other.reads
        self.writes -= other.writes
        self.total -= other.total
        return self


def get_stat_value(stat_dict: dict, key: str):
    idx = key.index("[")
    unit = UnitType(key[idx:])
    return parse_value(stat_dict[key], unit)


def parse_value(value: str, unit_type: UnitType) -> int | float | Size | timedelta | str:
    match unit_type:
        case UnitType.requests:
            stat_unit = int(value)
        case UnitType.percentage:
            stat_unit = float(value)
        case UnitType.block_4k:
            stat_unit = Size(float(value), Unit.Blocks4096)
        case UnitType.mebibyte:
            stat_unit = Size(float(value), Unit.MebiByte)
        case UnitType.kibibyte:
            stat_unit = Size(float(value), Unit.KibiByte)
        case UnitType.gibibyte:
            stat_unit = Size(float(value), Unit.GibiByte)
        case UnitType.seconds:
            stat_unit = timedelta(seconds=float(value))
        case _:
            stat_unit = value
    return stat_unit


def _get_section_filters(filter: List[StatsFilter], io_class_stats: bool = False):
    if filter is None or StatsFilter.all in filter:
        filters = [
            StatsFilter.conf,
            StatsFilter.usage,
            StatsFilter.req,
            StatsFilter.blk,
            StatsFilter.err,
        ]
    else:
        filters = filter
    if io_class_stats and StatsFilter.err in filters:
        filters.remove(StatsFilter.err)
    return filters


def get_stats_dict(
    filter: List[StatsFilter], cache_id: int, core_id: int = None, io_class_id: int = None
):
    csv_stats = casadm.print_statistics(
        cache_id=cache_id,
        core_id=core_id,
        io_class_id=io_class_id,
        filter=filter,
        output_format=casadm.OutputFormat.csv,
    ).stdout.splitlines()
    stat_keys, stat_values = csv.reader(csv_stats)
    # Unify names in block stats for core and cache to easier compare
    # cache vs core stats using unified key
    # cache stats: Reads from core(s)
    # core stats: Reads from core
    stat_keys = [x.replace("(s)", "") for x in stat_keys]
    stats_dict = dict(zip(stat_keys, stat_values))
    return stats_dict
