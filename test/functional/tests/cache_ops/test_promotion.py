#
# Copyright(c) 2024-2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import math
import random
import pytest

from api.cas import casadm
from api.cas.cache_config import SeqCutOffPolicy, CleaningPolicy, PromotionPolicy, \
    PromotionParametersNhit, CacheMode
from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.udev import Udev
from type_def.size import Size, Unit


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_promotion_policy_nhit_threshold():
    """
    title: Functional test for promotion policy nhit - threshold
    description: |
        Test checking if data is cached only after number of hits to given cache line
        accordingly to specified promotion nhit threshold.
    pass_criteria:
      - Promotion policy and hit parameters are set properly
      - Data is cached only after number of hits to given cache line specified by threshold param
      - Data is written in pass-through before number of hits to given cache line specified by
        threshold param
      - After meeting specified number of hits to given cache line, writes to other cache lines
        are handled in pass-through
    """
    random_thresholds = random.sample(range(2, 1000), 10)
    additional_writes_count = 10

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(value=5, unit=Unit.GibiByte)])
        core_device.create_partitions([Size(value=10, unit=Unit.GibiByte)])

        cache_part = cache_device.partitions[0]
        core_parts = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB)
        core = cache.add_core(core_parts)

    with TestRun.step("Disable sequential cut-off and cleaning"):
        cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        cache.set_cleaning_policy(CleaningPolicy.nop)
        cache.reset_counters()

    with TestRun.step("Check if statistics of writes to cache and writes to core are zeros"):
        check_statistics(
            cache,
            expected_writes_to_cache=Size.zero(),
            expected_writes_to_core=Size.zero()
        )

    with TestRun.step("Set nhit promotion policy"):
        cache.set_promotion_policy(PromotionPolicy.nhit)

    for iteration, threshold in enumerate(
            TestRun.iteration(
                random_thresholds,
                "Set and validate nhit promotion policy threshold"
            )
    ):
        with TestRun.step(f"Set threshold to {threshold} and trigger to 0%"):
            cache.set_params_nhit(
                PromotionParametersNhit(
                    threshold=threshold,
                    trigger=0
                )
            )

        with TestRun.step("Purge cache"):
            cache.purge_cache()

        with TestRun.step("Reset counters"):
            cache.reset_counters()

        with TestRun.step(
                "Run dd and check if number of writes to cache and writes to core increase "
                "accordingly to nhit parameters"
        ):
            # dd_seek is counted as below to use different part of the cache in each iteration
            dd_seek = int(
                cache.size.get_value(Unit.Blocks4096) // len(random_thresholds) * iteration
            )

            for count in range(1, threshold + additional_writes_count):
                Dd().input("/dev/random") \
                    .output(core.path) \
                    .oflag("direct") \
                    .block_size(Size(1, Unit.Blocks4096)) \
                    .count(1) \
                    .seek(dd_seek) \
                    .run()
                if count < threshold:
                    expected_writes_to_cache = Size.zero()
                    expected_writes_to_core = Size(count, Unit.Blocks4096)
                else:
                    expected_writes_to_cache = Size(count - threshold + 1, Unit.Blocks4096)
                    expected_writes_to_core = Size(threshold - 1, Unit.Blocks4096)
                check_statistics(cache, expected_writes_to_cache, expected_writes_to_core)

        with TestRun.step("Write to other cache line and check if it was handled in pass-through"):
            Dd().input("/dev/random") \
                .output(core.path) \
                .oflag("direct") \
                .block_size(Size(1, Unit.Blocks4096)) \
                .count(1) \
                .seek(int(dd_seek + Unit.Blocks4096.value)) \
                .run()
            expected_writes_to_core = expected_writes_to_core + Size(1, Unit.Blocks4096)
            check_statistics(cache, expected_writes_to_cache, expected_writes_to_core)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_promotion_policy_nhit_trigger():
    """
    title: Functional test for promotion policy nhit - trigger
    description: |
        Test checking if data is cached accordingly to nhit threshold parameter only after reaching
        cache occupancy specified by nhit trigger value
    pass_criteria:
      - Promotion policy and hit parameters are set properly
      - Data is cached accordingly to nhit threshold parameter only after reaching
        cache occupancy specified by nhit trigger value
      - Data is cached without nhit policy before reaching the trigger
    """
    random_triggers = random.sample(range(0, 100), 10)
    threshold = 2

    with TestRun.step("Prepare cache and core devices"):
        cache_device = TestRun.disks["cache"]
        core_device = TestRun.disks["core"]

        cache_device.create_partitions([Size(value=50, unit=Unit.MebiByte)])
        core_device.create_partitions([Size(value=100, unit=Unit.MebiByte)])

        cache_part = cache_device.partitions[0]
        core_parts = core_device.partitions[0]

    with TestRun.step("Disable udev"):
        Udev.disable()

    for trigger in TestRun.iteration(
            random_triggers,
            "Validate nhit promotion policy trigger"
    ):
        with TestRun.step("Start cache and add core"):
            cache = casadm.start_cache(cache_part, cache_mode=CacheMode.WB, force=True)
            core = cache.add_core(core_parts)

        with TestRun.step("Disable sequential cut-off and cleaning"):
            cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
            cache.set_cleaning_policy(CleaningPolicy.nop)

        with TestRun.step("Purge cache"):
            cache.purge_cache()

        with TestRun.step("Reset counters"):
            cache.reset_counters()

        with TestRun.step("Check if statistics of writes to cache and writes to core are zeros"):
            check_statistics(
                cache,
                expected_writes_to_cache=Size.zero(),
                expected_writes_to_core=Size.zero()
            )

        with TestRun.step("Set nhit promotion policy"):
            cache.set_promotion_policy(PromotionPolicy.nhit)

        with TestRun.step(f"Set threshold to {threshold} and trigger to {trigger}%"):
            cache.set_params_nhit(
                PromotionParametersNhit(
                    threshold=threshold,
                    trigger=trigger
                )
            )

        with TestRun.step(f"Run dd to fill {trigger}% of cache size with data"):
            blocks_count = math.ceil(cache.size.get_value(Unit.Blocks4096) * trigger / 100)
            Dd().input("/dev/random") \
                .output(core.path) \
                .oflag("direct") \
                .block_size(Size(1, Unit.Blocks4096)) \
                .count(blocks_count) \
                .seek(0) \
                .run()

        with TestRun.step("Check if all written data was cached"):
            check_statistics(
                cache,
                expected_writes_to_cache=Size(blocks_count, Unit.Blocks4096),
                expected_writes_to_core=Size.zero()
            )

        with TestRun.step("Write to free cached volume sectors"):
            free_seek = (blocks_count + 1)
            pt_blocks_count = int(cache.size.get_value(Unit.Blocks4096) - blocks_count)
            Dd().input("/dev/random") \
                .output(core.path) \
                .oflag("direct") \
                .block_size(Size(1, Unit.Blocks4096)) \
                .count(pt_blocks_count) \
                .seek(free_seek) \
                .run()

        with TestRun.step("Check if recently written data was written in pass-through"):
            check_statistics(
                cache,
                expected_writes_to_cache=Size(blocks_count, Unit.Blocks4096),
                expected_writes_to_core=Size(pt_blocks_count, Unit.Blocks4096)
            )

        with TestRun.step("Write to recently written sectors one more time"):
            Dd().input("/dev/random") \
                .output(core.path) \
                .oflag("direct") \
                .block_size(Size(1, Unit.Blocks4096)) \
                .count(pt_blocks_count) \
                .seek(free_seek) \
                .run()

        with TestRun.step("Check if recently written data was cached"):
            check_statistics(
                cache,
                expected_writes_to_cache=Size(blocks_count + pt_blocks_count, Unit.Blocks4096),
                expected_writes_to_core=Size(pt_blocks_count, Unit.Blocks4096)
            )

        with TestRun.step("Stop cache"):
            cache.stop(no_data_flush=True)


def check_statistics(cache, expected_writes_to_cache, expected_writes_to_core):
    cache_stats = cache.get_statistics()
    writes_to_cache = cache_stats.block_stats.cache.writes
    writes_to_core = cache_stats.block_stats.core.writes

    if writes_to_cache != expected_writes_to_cache:
        TestRun.LOGGER.error(
            f"Number of writes to cache should be "
            f"{expected_writes_to_cache.get_value(Unit.Blocks4096)} "
            f"but it is {writes_to_cache.get_value(Unit.Blocks4096)}")
    if writes_to_core != expected_writes_to_core:
        TestRun.LOGGER.error(
            f"Number of writes to core should be: "
            f"{expected_writes_to_core.get_value(Unit.Blocks4096)} "
            f"but it is {writes_to_core.get_value(Unit.Blocks4096)}")
