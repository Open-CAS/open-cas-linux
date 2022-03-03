#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

# Order in arrays is important!
config_stats_cache = [
    "cache id", "cache size", "cache device", "exported object", "core devices",
    "inactive core devices", "write policy", "cleaning policy", "promotion policy",
    "cache line size", "metadata memory footprint", "dirty for", "status"
]
config_stats_core = [
    "core id", "core device", "exported object", "core size", "dirty for", "status",
    "seq cutoff threshold", "seq cutoff policy"
]
config_stats_ioclass = ["io class id", "io class name", "eviction priority", "max size"]
usage_stats = ["occupancy", "free", "clean", "dirty"]
usage_stats_ioclass = ["occupancy", "clean", "dirty"]
inactive_usage_stats = ["inactive occupancy", "inactive clean", "inactive dirty"]
request_stats = [
    "read hits", "read partial misses", "read full misses", "read total",
    "write hits", "write partial misses", "write full misses", "write total",
    "pass-through reads", "pass-through writes",
    "serviced requests", "total requests"
]
block_stats_cache = [
    "reads from core(s)", "writes to core(s)", "total to/from core(s)",
    "reads from cache", "writes to cache", "total to/from cache",
    "reads from exported object(s)", "writes to exported object(s)",
    "total to/from exported object(s)"
]
block_stats_core = [stat.replace("(s)", "") for stat in block_stats_cache]
error_stats = [
    "cache read errors", "cache write errors", "cache total errors",
    "core read errors", "core write errors", "core total errors",
    "total errors"
]


class CacheStats:
    stats_list = [
        "config_stats",
        "usage_stats",
        "inactive_usage_stats",
        "request_stats",
        "block_stats",
        "error_stats",
    ]

    def __init__(self, stats):
        try:
            self.config_stats = CacheConfigStats(
                *[stats[stat] for stat in config_stats_cache]
            )
        except KeyError:
            pass
        try:
            self.usage_stats = UsageStats(
                *[stats[stat] for stat in usage_stats]
            )
        except KeyError:
            pass
        try:
            self.inactive_usage_stats = InactiveUsageStats(
                *[stats[stat] for stat in inactive_usage_stats]
            )
        except KeyError:
            pass
        try:
            self.request_stats = RequestStats(
                *[stats[stat] for stat in request_stats]
            )
        except KeyError:
            pass
        try:
            self.block_stats = BlockStats(
                *[stats[stat] for stat in block_stats_cache]
            )
        except KeyError:
            pass
        try:
            self.error_stats = ErrorStats(
                *[stats[stat] for stat in error_stats]
            )
        except KeyError:
            pass

    def __str__(self):
        status = ""
        for stats_item in self.stats_list:
            current_stat = getattr(self, stats_item, None)
            if current_stat:
                status += f"--- Cache {current_stat}"
        return status

    def __eq__(self, other):
        if not other:
            return False
        for stats_item in self.stats_list:
            if getattr(self, stats_item, None) != getattr(other, stats_item, None):
                return False
        return True


class CoreStats:
    stats_list = [
        "config_stats",
        "usage_stats",
        "request_stats",
        "block_stats",
        "error_stats",
    ]

    def __init__(self, stats):
        try:
            self.config_stats = CoreConfigStats(
                *[stats[stat] for stat in config_stats_core]
            )
        except KeyError:
            pass
        try:
            self.usage_stats = UsageStats(
                *[stats[stat] for stat in usage_stats]
            )
        except KeyError:
            pass
        try:
            self.request_stats = RequestStats(
                *[stats[stat] for stat in request_stats]
            )
        except KeyError:
            pass
        try:
            self.block_stats = BlockStats(
                *[stats[stat] for stat in block_stats_core]
            )
        except KeyError:
            pass
        try:
            self.error_stats = ErrorStats(
                *[stats[stat] for stat in error_stats]
            )
        except KeyError:
            pass

    def __str__(self):
        status = ""
        for stats_item in self.stats_list:
            current_stat = getattr(self, stats_item, None)
            if current_stat:
                status += f"--- Core {current_stat}"
        return status

    def __eq__(self, other):
        if not other:
            return False
        for stats_item in self.stats_list:
            if getattr(self, stats_item, None) != getattr(other, stats_item, None):
                return False
        return True


class IoClassStats:
    stats_list = [
        "config_stats",
        "usage_stats",
        "request_stats",
        "block_stats",
    ]

    def __init__(self, stats, block_stats_list):
        try:
            self.config_stats = IoClassConfigStats(
                *[stats[stat] for stat in config_stats_ioclass]
            )
        except KeyError:
            pass
        try:
            self.usage_stats = IoClassUsageStats(
                *[stats[stat] for stat in usage_stats_ioclass]
            )
        except KeyError:
            pass
        try:
            self.request_stats = RequestStats(
                *[stats[stat] for stat in request_stats]
            )
        except KeyError:
            pass
        try:
            self.block_stats = BlockStats(
                *[stats[stat] for stat in block_stats_list]
            )
        except KeyError:
            pass

    def __str__(self):
        status = ""
        for stats_item in self.stats_list:
            current_stat = getattr(self, stats_item, None)
            if current_stat:
                status += f"--- IO class {current_stat}"
        return status

    def __eq__(self, other):
        if not other:
            return False
        for stats_item in self.stats_list:
            if getattr(self, stats_item, None) != getattr(other, stats_item, None):
                return False
        return True


class CacheIoClassStats(IoClassStats):
    def __init__(self, stats):
        super().__init__(stats, block_stats_cache)


class CoreIoClassStats(IoClassStats):
    def __init__(self, stats):
        super().__init__(stats, block_stats_core)


class CacheConfigStats:
    def __init__(
        self,
        cache_id,
        cache_size,
        cache_dev,
        exp_obj,
        core_dev,
        inactive_core_dev,
        write_policy,
        cleaning_policy,
        promotion_policy,
        cache_line_size,
        metadata_memory_footprint,
        dirty_for,
        status,
    ):
        self.cache_id = cache_id
        self.cache_size = cache_size
        self.cache_dev = cache_dev
        self.exp_obj = exp_obj
        self.core_dev = core_dev
        self.inactive_core_dev = inactive_core_dev
        self.write_policy = write_policy
        self.cleaning_policy = cleaning_policy
        self.promotion_policy = promotion_policy
        self.cache_line_size = cache_line_size
        self.metadata_memory_footprint = metadata_memory_footprint
        self.dirty_for = dirty_for
        self.status = status

    def __str__(self):
        return (
            f"Config stats:\n"
            f"Cache ID: {self.cache_id}\n"
            f"Cache size: {self.cache_size}\n"
            f"Cache device: {self.cache_dev}\n"
            f"Exported object: {self.exp_obj}\n"
            f"Core devices: {self.core_dev}\n"
            f"Inactive core devices: {self.inactive_core_dev}\n"
            f"Write policy: {self.write_policy}\n"
            f"Cleaning policy: {self.cleaning_policy}\n"
            f"Promotion policy: {self.promotion_policy}\n"
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
            and self.inactive_core_dev == other.inactive_core_dev
            and self.write_policy == other.write_policy
            and self.cleaning_policy == other.cleaning_policy
            and self.promotion_policy == other.promotion_policy
            and self.cache_line_size == other.cache_line_size
            and self.metadata_memory_footprint == other.metadata_memory_footprint
            and self.dirty_for == other.dirty_for
            and self.status == other.status
        )


class CoreConfigStats:
    def __init__(
        self,
        core_id,
        core_dev,
        exp_obj,
        core_size,
        dirty_for,
        status,
        seq_cutoff_threshold,
        seq_cutoff_policy,
    ):
        self.core_id = core_id
        self.core_dev = core_dev
        self.exp_obj = exp_obj
        self.core_size = core_size
        self.dirty_for = dirty_for
        self.status = status
        self.seq_cutoff_threshold = seq_cutoff_threshold
        self.seq_cutoff_policy = seq_cutoff_policy

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


class IoClassConfigStats:
    def __init__(
        self, io_class_id, io_class_name, eviction_priority, selective_allocation
    ):
        self.io_class_id = io_class_id
        self.io_class_name = io_class_name
        self.eviction_priority = eviction_priority
        self.selective_allocation = selective_allocation

    def __str__(self):
        return (
            f"Config stats:\n"
            f"IO class ID: {self.io_class_id}\n"
            f"IO class name: {self.io_class_name}\n"
            f"Eviction priority: {self.eviction_priority}\n"
            f"Selective allocation: {self.selective_allocation}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.io_class_id == other.io_class_id
            and self.io_class_name == other.io_class_name
            and self.eviction_priority == other.eviction_priority
            and self.selective_allocation == other.selective_allocation
        )


class UsageStats:
    def __init__(self, occupancy, free, clean, dirty):
        self.occupancy = occupancy
        self.free = free
        self.clean = clean
        self.dirty = dirty

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

    def __add__(self, other):
        return UsageStats(
            self.occupancy + other.occupancy,
            self.free + other.free,
            self.clean + other.clean,
            self.dirty + other.dirty
        )

    def __iadd__(self, other):
        self.occupancy += other.occupancy
        self.free += other.free
        self.clean += other.clean
        self.dirty += other.dirty
        return self


class IoClassUsageStats:
    def __init__(self, occupancy, clean, dirty):
        self.occupancy = occupancy
        self.clean = clean
        self.dirty = dirty

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

    def __add__(self, other):
        return UsageStats(
            self.occupancy + other.occupancy,
            self.clean + other.clean,
            self.dirty + other.dirty
        )

    def __iadd__(self, other):
        self.occupancy += other.occupancy
        self.clean += other.clean
        self.dirty += other.dirty
        return self


class InactiveUsageStats:
    def __init__(self, inactive_occupancy, inactive_clean, inactive_dirty):
        self.inactive_occupancy = inactive_occupancy
        self.inactive_clean = inactive_clean
        self.inactive_dirty = inactive_dirty

    def __str__(self):
        return (
            f"Inactive usage stats:\n"
            f"Inactive occupancy: {self.inactive_occupancy}\n"
            f"Inactive clean: {self.inactive_clean}\n"
            f"Inactive dirty: {self.inactive_dirty}\n"
        )

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.inactive_occupancy == other.inactive_occupancy
            and self.inactive_clean == other.inactive_clean
            and self.inactive_dirty == other.inactive_dirty
        )


class RequestStats:
    def __init__(
        self,
        read_hits,
        read_part_misses,
        read_full_misses,
        read_total,
        write_hits,
        write_part_misses,
        write_full_misses,
        write_total,
        pass_through_reads,
        pass_through_writes,
        requests_serviced,
        requests_total,
    ):
        self.read = RequestStatsChunk(
            read_hits, read_part_misses, read_full_misses, read_total
        )
        self.write = RequestStatsChunk(
            write_hits, write_part_misses, write_full_misses, write_total
        )
        self.pass_through_reads = pass_through_reads
        self.pass_through_writes = pass_through_writes
        self.requests_serviced = requests_serviced
        self.requests_total = requests_total

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


class RequestStatsChunk:
    def __init__(self, hits, part_misses, full_misses, total):
        self.hits = hits
        self.part_misses = part_misses
        self.full_misses = full_misses
        self.total = total

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


class BlockStats:
    def __init__(
        self,
        core_reads,
        core_writes,
        core_total,
        cache_reads,
        cache_writes,
        cache_total,
        exp_obj_reads,
        exp_obj_writes,
        exp_obj_total,
    ):
        self.core = BasicStatsChunk(core_reads, core_writes, core_total)
        self.cache = BasicStatsChunk(cache_reads, cache_writes, cache_total)
        self.exp_obj = BasicStatsChunk(exp_obj_reads, exp_obj_writes, exp_obj_total)

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
            self.core == other.core
            and self.cache == other.cache
            and self.exp_obj == other.exp_obj
        )


class ErrorStats:
    def __init__(
        self,
        cache_read_errors,
        cache_write_errors,
        cache_total_errors,
        core_read_errors,
        core_write_errors,
        core_total_errors,
        total_errors,
    ):
        self.cache = BasicStatsChunk(
            cache_read_errors, cache_write_errors, cache_total_errors
        )
        self.core = BasicStatsChunk(
            core_read_errors, core_write_errors, core_total_errors
        )
        self.total_errors = total_errors

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


class BasicStatsChunk:
    def __init__(self, reads, writes, total):
        self.reads = reads
        self.writes = writes
        self.total = total

    def __str__(self):
        return f"Reads: {self.reads}\nWrites: {self.writes}\nTotal: {self.total}\n"

    def __eq__(self, other):
        if not other:
            return False
        return (
            self.reads == other.reads
            and self.writes == other.writes
            and self.total == other.total
        )
