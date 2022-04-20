#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from aenum import Enum, IntFlag

from test_utils.os_utils import get_kernel_module_parameter
from test_utils.size import Size, Unit
from test_utils.time import Time


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
    standby = "standby"
    standby_detached = "standby detached"

    def __str__(self):
        return self.value


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
    def __init__(self, policy=None, threshold=None, promotion_count=None):
        self.policy = policy
        self.threshold = threshold
        self.promotion_count = promotion_count

    def __eq__(self, other):
        return (
            self.policy == other.policy
            and self.threshold == other.threshold
            and self.promotion_count == other.promotion_count
        )

    @staticmethod
    def default_seq_cut_off_params():
        return SeqCutOffParameters(
            threshold=Size(1024, Unit.KibiByte),
            policy=SeqCutOffPolicy.full,
            promotion_count=8
        )


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


# Specify how IO requests unaligned to 4KiB should be handled
class UnalignedIo(Enum):
    PT = 0      # use PT mode
    cache = 1   # use current cache mode
    DEFAULT = cache


# Specify if IO scheduler will be used when handling IO requests
class UseIoScheduler(Enum):
    off = 0
    on = 1
    DEFAULT = on


class KernelParameters:
    seq_cut_off_mb_DEFAULT = 1
    max_writeback_queue_size_DEFAULT = 65536
    writeback_queue_unblock_size_DEFAULT = 60000

    def __init__(
            self,
            unaligned_io: UnalignedIo = None,
            use_io_scheduler: UseIoScheduler = None,
            seq_cut_off_mb: int = None,
            max_writeback_queue_size: int = None,
            writeback_queue_unblock_size: int = None
    ):
        self.unaligned_io = unaligned_io
        self.use_io_scheduler = use_io_scheduler
        # Specify default sequential cut off threshold value in MiB
        # 0 - sequential cut off disabled, 1 or larger = sequential cut off threshold (default is 1)
        self.seq_cut_off_mb = seq_cut_off_mb
        # Specify optimal write queue size, default - 65536
        self.max_writeback_queue_size = max_writeback_queue_size
        # Specify unblock threshold for write queue, default - 60000
        self.writeback_queue_unblock_size = writeback_queue_unblock_size

    def __eq__(self, other):
        return (
            equal_or_default(self.unaligned_io, other.unaligned_io, UnalignedIo.DEFAULT)
            and equal_or_default(
                self.use_io_scheduler, other.use_io_scheduler, UseIoScheduler.DEFAULT
            )
            and equal_or_default(
                self.seq_cut_off_mb, other.seq_cut_off_mb,
                self.seq_cut_off_mb_DEFAULT
            )
            and equal_or_default(
                self.max_writeback_queue_size, other.max_writeback_queue_size,
                self.max_writeback_queue_size_DEFAULT
            )
            and equal_or_default(
                self.writeback_queue_unblock_size, other.writeback_queue_unblock_size,
                self.writeback_queue_unblock_size_DEFAULT
            )
        )

    @classmethod
    def DEFAULT(cls):
        return KernelParameters(
            UnalignedIo.DEFAULT,
            UseIoScheduler.DEFAULT,
            cls.seq_cut_off_mb_DEFAULT,
            cls.max_writeback_queue_size_DEFAULT,
            cls.writeback_queue_unblock_size_DEFAULT
        )

    @staticmethod
    def read_current_settings():
        module = "cas_cache"
        return KernelParameters(
            UnalignedIo(int(get_kernel_module_parameter(module, "unaligned_io"))),
            UseIoScheduler(int(get_kernel_module_parameter(module, "use_io_scheduler"))),
            int(get_kernel_module_parameter(module, "seq_cut_off_mb")),
            int(get_kernel_module_parameter(module, "max_writeback_queue_size")),
            int(get_kernel_module_parameter(module, "writeback_queue_unblock_size"))
        )

    def get_parameter_dictionary(self):
        params = {}
        if self.unaligned_io not in [None, UnalignedIo.DEFAULT]:
            params["unaligned_io"] = str(self.unaligned_io.value)
        if self.use_io_scheduler not in [None, UseIoScheduler.DEFAULT]:
            params["use_io_scheduler"] = str(self.use_io_scheduler.value)
        if self.seq_cut_off_mb not in [None, self.seq_cut_off_mb_DEFAULT]:
            params["seq_cut_off_mb"] = str(self.seq_cut_off_mb)
        if self.max_writeback_queue_size not in [None, self.max_writeback_queue_size_DEFAULT]:
            params["max_writeback_queue_size"] = str(self.max_writeback_queue_size)
        if (self.writeback_queue_unblock_size not in
                [None, self.writeback_queue_unblock_size_DEFAULT]):
            params["writeback_queue_unblock_size"] = str(self.writeback_queue_unblock_size)
        return params


# TODO: Use case for this will be to iterate over configurations (kernel params such as
# TODO: io scheduler, metadata layout) and prepare env before starting cache
class CacheConfig:
    def __init__(
        self,
        cache_line_size=CacheLineSize.DEFAULT,
        cache_mode=CacheMode.DEFAULT,
        cleaning_policy=CleaningPolicy.DEFAULT,
        kernel_parameters=None
    ):
        self.cache_line_size = cache_line_size
        self.cache_mode = cache_mode
        self.cleaning_policy = cleaning_policy
        self.kernel_parameters = kernel_parameters

    def __eq__(self, other):
        return (
            self.cache_line_size == other.cache_line_size
            and self.cache_mode == other.cache_mode
            and self.cleaning_policy == other.cleaning_policy
            and equal_or_default(
                self.kernel_parameters, other.kernel_parameters, KernelParameters.DEFAULT
            )
        )


def equal_or_default(item1, item2, default):
    return (item1 if item1 is not None else default) == (item2 if item2 is not None else default)
