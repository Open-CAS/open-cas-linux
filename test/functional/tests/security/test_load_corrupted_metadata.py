#
# Copyright(c) 2021 Intel Corporation
# Copyright(c) 2023-2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import random

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    CleaningPolicy,
    PromotionPolicy,
    SeqCutOffPolicy,
)
from storage_devices.device import Device
from core.test_run import TestRun
from storage_devices.ramdisk import RamDisk
from test_tools.dd import Dd
from test_utils.output import CmdException
from test_utils.size import Size, Unit


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("promotion_policy", PromotionPolicy)
@pytest.mark.parametrizex("seq_cutoff_policy", SeqCutOffPolicy)
def test_load_corrupted_metadata(cache_mode, cache_line_size, cleaning_policy,
                                 promotion_policy, seq_cutoff_policy):
    """
        title: Security test for loading cache with corrupted metadata.
        description: |
            Validate the ability of Open CAS to load cache instance and work if metadata
            is corrupted.
        pass_criteria:
          - If metadata is recognized as corrupted, load operation should be aborted.
          - If not then executing I/O operations on CAS device should not result in kernel panic.
    """

    iteration_per_config = 1000

    with TestRun.step("Prepare RAM devices for test."):
        cache_dev, core_dev = RamDisk.create(disk_size=Size(100, Unit.MiB), disk_count=2)

    for iteration in TestRun.iteration(
            range(iteration_per_config),
            f"Corrupt metadata {iteration_per_config} times."
    ):

        with TestRun.step("Prepare cache and core."):
            cache = casadm.start_cache(cache_dev, cache_mode, cache_line_size, force=True)
            core = casadm.add_core(cache, core_dev)
            metadata_size = int(cache.get_metadata_size_on_disk().get_value())

        with TestRun.step("Configure cache."):
            cache.set_cleaning_policy(cleaning_policy)
            cache.set_promotion_policy(promotion_policy)
            cache.set_seq_cutoff_policy(seq_cutoff_policy)

        with TestRun.step("Write random data to CAS device."):
            Dd().input('/dev/urandom') \
                .output(core.path) \
                .block_size(Size(1, Unit.Blocks512)) \
                .oflag('direct') \
                .run()

        with TestRun.step("Stop cache without flush."):
            cache.stop(no_data_flush=True)

        with TestRun.step("Corrupt metadata."):
            corrupt_metadata(cache_dev, iteration, metadata_size)

        with TestRun.step("Try to load cache."):
            loaded = False
            try:
                casadm.load_cache(cache_dev)
                loaded = True
                TestRun.LOGGER.info("Cache is loaded.")
            except CmdException:
                TestRun.LOGGER.info("Cache is not loaded.")

        if loaded:
            with TestRun.step("Run random I/O traffic to cached volume."):
                try:
                    Dd().input('/dev/urandom') \
                        .output(core.path) \
                        .block_size(Size(1, Unit.Blocks512)) \
                        .oflag('direct') \
                        .run()
                except CmdException:
                    TestRun.LOGGER.error("Sending I/O requests to cached volume caused error.")
                    cache.stop()
                    break

            with TestRun.step("Stop cache."):
                cache.stop()


def corrupt_metadata(cache_dev: Device, iteration: int, metadata_size: int):
    superblock_max_bytes = int(Size(8, Unit.KiB).get_value())
    number_of_bits_to_corrupt = random.randint(1, 10)
    corrupted_bytes = []
    for i in range(number_of_bits_to_corrupt):
        random_mask = 1 << random.randrange(0, 7)
        random_offset = random.randrange(
            0, superblock_max_bytes if iteration % 100 == 0 else metadata_size
        )
        corrupted_bytes.append(random_offset)
        corrupt_bits(cache_dev, random_mask, random_offset)
    corrupted_bytes.sort()
    TestRun.LOGGER.info(f"Corrupted bytes: {corrupted_bytes}")


def corrupt_bits(cache_dev: Device, mask: int, offset: int):
    output = TestRun.executor.run(f"xxd -bits -len 1 -seek {offset} -postscript {cache_dev.path}")
    corrupt_cmd = (f"printf '%02x' $((0x{output.stdout}^{mask})) | "
                   f"xxd -revert -postscript -seek {offset} - {cache_dev.path}")
    TestRun.executor.run_expect_success(corrupt_cmd)
