#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from aenum import Enum, IntFlag
from attotime import attotimedelta

from test_utils.size import Size, Unit


class CacheLineSize(Enum):
    LINE_4KiB = Size(4, Unit.KibiByte)
    LINE_8KiB = Size(8, Unit.KibiByte)
    LINE_16KiB = Size(16, Unit.KibiByte)
    LINE_32KiB = Size(32, Unit.KibiByte)
    LINE_64KiB = Size(64, Unit.KibiByte)
    DEFAULT = LINE_4KiB

    def __int__(self):
        return int(self.value.get_value())


class CacheModeTrait(IntFlag):
    InsertWrite = 1
    InsertRead = 2
    LazyWrites = 4


class CacheMode(Enum):
    WT = "Write-Through"
    WB = "Write-Back"
    WA = "Write-Around"
    PT = "Pass-Through"
    WO = "Write-Only"
    DEFAULT = WT

    def __str__(self):
        return self.value

    @staticmethod
    def get_traits(cache_mode):
        if cache_mode == CacheMode.PT:
            return CacheModeTrait(0)
        elif cache_mode == CacheMode.WT:
            return CacheModeTrait.InsertRead | CacheModeTrait.InsertWrite
        elif cache_mode == CacheMode.WB:
            return (
                CacheModeTrait.InsertRead | CacheModeTrait.InsertWrite | CacheModeTrait.LazyWrites
            )
        elif cache_mode == CacheMode.WO:
            return CacheModeTrait.InsertWrite | CacheModeTrait.LazyWrites
        elif cache_mode == CacheMode.WA:
            return CacheModeTrait.InsertRead

    @staticmethod
    def with_traits(flags: CacheModeTrait):
        return [
            m for m in CacheMode if all(map(lambda t: t in CacheMode.get_traits(m), flags))
        ]

    @staticmethod
    def with_any_trait(flags: CacheModeTrait):
        return [
            m for m in CacheMode if any(map(lambda t: t in CacheMode.get_traits(m), flags))
        ]


class SeqCutOffPolicy(Enum):
    full = 0
    always = 1
    never = 2
    DEFAULT = full

    @classmethod
    def from_name(cls, name):
        for policy_name, policy in SeqCutOffPolicy.__members__.items():
            if name == policy_name:
                return policy

        raise ValueError(f"{name} is not a valid sequential cut off name")


class EvictionPolicy(Enum):
    lru = "LRU"
    DEFAULT = lru

    def __str__(self):
        return self.value


class MetadataMode(Enum):
    normal = "normal"
    atomic = "atomic"
    DEFAULT = normal

    def __str__(self):
        return self.value


class CleaningPolicy(Enum):
    alru = "ALRU"
    nop = "NOP"
    acp = "ACP"
    DEFAULT = alru

    def __str__(self):
        return self.value


class PromotionPolicy(Enum):
    always = "always"
    nhit = "nhit"
    DEFAULT = always

    def __str__(self):
        return self.value


class CacheStatus(Enum):
    not_running = "not running"
    running = "running"
    stopping = "stopping"
    initializing = "initializing"
    flushing = "flushing"
    incomplete = "incomplete"

    def __str__(self):
        return self.value


class Time(attotimedelta):
    def total_milliseconds(self):
        return int(self.total_seconds() * 1000)


class FlushParametersAlru:
    def __init__(
        self,
        activity_threshold=None,
        flush_max_buffers=None,
        staleness_time=None,
        wake_up_time=None,
    ):
        self.activity_threshold = activity_threshold
        self.flush_max_buffers = flush_max_buffers
        self.staleness_time = staleness_time
        self.wake_up_time = wake_up_time

    def __eq__(self, other):
        return (
            self.activity_threshold == other.activity_threshold
            and self.flush_max_buffers == other.flush_max_buffers
            and self.staleness_time == other.staleness_time
            and self.wake_up_time == other.wake_up_time
        )

    @staticmethod
    def alru_params_range():
        alru_params = FlushParametersAlru()
        alru_params.activity_threshold = (0, 1000000)
        alru_params.flush_max_buffers = (1, 10000)
        alru_params.staleness_time = (1, 3600)
        alru_params.wake_up_time = (0, 3600)
        return alru_params

    def __eq__(self, other):
        return self.activity_threshold == other.activity_threshold and \
            self.flush_max_buffers == other.flush_max_buffers and \
            self.staleness_time == other.staleness_time and \
            self.wake_up_time == other.wake_up_time

    @staticmethod
    def default_alru_params():
        alru_params = FlushParametersAlru()
        alru_params.activity_threshold = Time(milliseconds=10000)
        alru_params.flush_max_buffers = 100
        alru_params.staleness_time = Time(seconds=120)
        alru_params.wake_up_time = Time(seconds=20)
        return alru_params


class FlushParametersAcp:
    def __init__(self, flush_max_buffers: int = None, wake_up_time: Time = None):
        self.flush_max_buffers = flush_max_buffers
        self.wake_up_time = wake_up_time

    def __eq__(self, other):
        return (
            self.flush_max_buffers == other.flush_max_buffers
            and self.wake_up_time == other.wake_up_time
        )

    def __str__(self):
        ret = ""
        if self.flush_max_buffers is not None:
            ret += f"acp flush max buffers value: {self.flush_max_buffers} "
        if self.wake_up_time is not None:
            ret += f"acp wake up time value: {self.wake_up_time.total_milliseconds()}"
        return ret

    @staticmethod
    def acp_params_range():
        acp_params = FlushParametersAcp()
        acp_params.flush_max_buffers = (1, 10000)
        acp_params.wake_up_time = (0, 10000)
        return acp_params

    def __eq__(self, other):
        return self.flush_max_buffers == other.flush_max_buffers and \
            self.wake_up_time == other.wake_up_time

    @staticmethod
    def default_acp_params():
        acp_params = FlushParametersAcp()
        acp_params.flush_max_buffers = 128
        acp_params.wake_up_time = Time(milliseconds=10)
        return acp_params


class SeqCutOffParameters:
    def __init__(self, policy=None, threshold=None):
        self.policy = policy
        self.threshold = threshold

    def __eq__(self, other):
        return (
            self.policy == other.policy
            and self.threshold == other.threshold
        )

    @staticmethod
    def default_seq_cut_off_params():
        seq_cut_off_params = SeqCutOffParameters()
        seq_cut_off_params.policy = SeqCutOffPolicy.full
        seq_cut_off_params.threshold = Size(1024, Unit.KibiByte)
        return seq_cut_off_params


class PromotionParametersNhit:
    def __init__(self, threshold=None, trigger=None):
        self.threshold = threshold
        self.trigger = trigger

    def __eq__(self, other):
        return (
            self.threshold == other.threshold
            and self.trigger == other.trigger
        )

    @staticmethod
    def nhit_params_range():
        nhit_params = PromotionParametersNhit()
        nhit_params.threshold = (2, 1000)
        nhit_params.trigger = (0, 100)
        return nhit_params

    @staticmethod
    def default_nhit_params():
        nhit_params = PromotionParametersNhit()
        nhit_params.threshold = 3
        nhit_params.trigger = 80
        return nhit_params


# TODO: Use case for this will be to iterate over configurations (kernel params such as
# TODO: io scheduler, metadata layout) and prepare env before starting cache
class CacheConfig:
    def __init__(
        self,
        cache_line_size=CacheLineSize.DEFAULT,
        cache_mode=CacheMode.DEFAULT,
        cleaning_policy=CleaningPolicy.DEFAULT,
        eviction_policy=EvictionPolicy.DEFAULT,
        metadata_mode=MetadataMode.normal,
    ):
        self.cache_line_size = cache_line_size
        self.cache_mode = cache_mode
        self.cleaning_policy = cleaning_policy
        self.eviction_policy = eviction_policy
        self.metadata_mode = metadata_mode

    def __eq__(self, other):
        return (
            self.cache_line_size == other.cache_line_size
            and self.cache_mode == other.cache_mode
            and self.cleaning_policy == other.cleaning_policy
            and self.eviction_policy == other.eviction_policy
            and self.metadata_mode == other.metadata_mode
        )
