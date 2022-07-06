#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas.cache_config import CacheMode, CleaningPolicy, CacheModeTrait, CacheLineSize


@pytest.mark.skip(reason="not implemented")
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", CleaningPolicy)
def test_failover_during_background_cleaning(pyocf_ctx, cache_mode, cls, cleaning_policy):
    """
    title: Failover sequence with background cleaning:
    description:
      Verify proper failover behaviour and data integrity after power failure during background
      cleaning running.
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes with lazy writes - to make sure dirty data is produced so that
        metadata synchronization between hosts occurs
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy - as different policies have separate metadata handling implementation
    steps:
      - On 2 DUTs (main and backup) prepare RAID1 cache devices of 1GiB size, comprising of 2
        Optane drives each.
      - On 2 DUTs (main and backup) prepare primary storage device of size 1.5GiB
      - On main DUT prefill primary storage device with random data
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start cache on top of cache DRBD device with parametrized cacheline size and cache mode
          - Set cleaning policy to NOP
          - Wait for DRBD synchronization
          - Fill cache with random 50% read/write mix workload, block size 4K
          - Verify cache is > 25% dirty
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to the parametrized cache mode without flush
          - Switch to parametrized cleaning policy
          - Wait for the background cleaner to start working (no wait for ACP, according to
            policy parameters for ALRU)
          - Verify cleaner is progressing by inspecting dirty statistics
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache RAID drive
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    pass


@pytest.mark.skip(reason="not implemented")
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
def test_failover_during_dirty_flush(pyocf_ctx, cache_mode, cls):
    """
    title: Failover sequence with after power failure during dirty data flush
    description:
      Verify proper failover behaviour and data integrity after power failure during
      user-issued cleaning
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes with lazy writes - to make sure dirty data is produced so that
        metadata synchronization between hosts occurs
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
    steps:
      - On 2 DUTs (main and backup) prepare RAID1 cache devices of 1GiB size, comprising of 2
        Optane drives each.
      - On 2 DUTs (main and backup) prepare primary storage device of size 1.5GiB
      - On main DUT prefill primary storage device with random data
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start cache on top of cache DRBD device with parametrized cacheline size and cache mode
          - Wait for DRBD synchronization
          - Set cleaning policy to NOP
          - Fill cache with random 50% read/write mix workload, block size 4K
          - Verify cache is > 25% dirty
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to the parametrized cache mode without flush
          - Issue cache flush command
          - Verify flush is progressing by inspecting dirty statistics
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache RAID drive
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    pass


@pytest.mark.skip(reason="not implemented")
@pytest.mark.multidut(2)
@pytest.mark.parametrize(
    "cache_mode", [m for m in CacheMode if m != CacheMode.WO and m != CacheMode.PT]
)
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", [c for c in CleaningPolicy if c != CleaningPolicy.alru])
def test_failover_during_io_with_eviction(pyocf_ctx, cache_mode, cls, cleaning_policy):
    """
    title: Failover sequence with after power failure during I/O with eviction
    description:
      Verify proper failover behaviour and data integrity after power failure during
      I/O handling with eviction
    pass_criteria:
      - Failover procedure success
      - Data integrity is maintained
    parametrizations:
      - cache mode: all cache modes except WO and PT - to trigger eviction via
        reads
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy: all except ALRU, as it doesn't do any cleaning in runtime
    steps:
      - On 2 DUTs (main and backup) prepare RAID1 cache devices of 1GiB size, comprising of 2
        Optane drives each.
      - On 2 DUTs (main and backup) prepare primary storage device of size 1.5GiB
      - On main DUT prefill primary storage device with random data
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start WB cache on top of cache DRBD device with parametrized cacheline size
          - Set cleaning policy to NOP
          - Wait for DRBD synchronization
          - Fill cache with random 50% read/write mix workload, block size = parametrized cache
            line size
          - Verify cache is > 25% dirty
          - Verify cache ocuppancy is 100%
          - Switch to WO cache mode without flush
          - Calculate checksum of CAS exported object
          - Switch back to parametrized cache mode without flush
          - Switch to parametrized cleaning policy and cache mode
          - Run multi-threaded I/O, 100% random read, block_size range [4K, parametrized cache line
            size] with 4K increment, different random seed than the previous prefill I/O, entire
            primary storage LBA address range, runtime 1h
          - Verify cache miss statistic is being incremented
          - Verify pass-through I/O statistic is not being incremented
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache RAID drive
          - calculate checksum of CAS exported object
      - Verify that the two checksums are equal
      - Power on the main DUT
    """
    pass


@pytest.mark.skip(reason="not implemented")
@pytest.mark.multidut(2)
@pytest.mark.parametrize("cls", [CacheLineSize.LINE_4KiB, CacheLineSize.LINE_64KiB])
@pytest.mark.parametrize("cleaning_policy", [c for c in CleaningPolicy if c != CleaningPolicy.alru])
def test_failover_io_long(pyocf_ctx, cls, cleaning_policy):
    """
    title:
        Failover WB I/O long
    Description:
         4h I/O with data verification in failover setup
    pass_criteria:
      - Data integrity is maintained
      - Failover procedure success
    parametrizations:
      - cacheline size: 4K, 64K - to test both sector I/O and full-cacheline I/O
      - cleaning policy: all except ALRU, as it doesn't do any cleaning in runtime
    steps:
      - On 2 DUTs (main and backup) prepare RAID1 cache devices of 1GiB size, comprising of 2
        Optane drives each.
      - On 2 DUTs (main and backup) prepare primary storage device of size 1.5GiB
      - Start a standby cache instance on the backup DUT with parametrized cacheline size
      - Configure DRBD to replicate cache and core storage from main to backup node
      - On main DUT:
          - Start WB cache on top of cache DRBD device with parametrized cacheline size
          - Set the parametrized cleaning policy
          - Create XFS file system on CAS exported object
          - Wait for DRBD synchronization
          - Mount file system
          - Run 4h FIO with data verification: random R/W, 16 jobs, filesystem, entire primary
            storage LBA address range, --bssplit=4k/10:8k/25:16k/25:32k/20:64k/10:128k/5:256k/5
          - Verify no data errors
          - Switch to WO cache mode without flush
          - Calculate checksum of fio test file(s)
          - Switch back to WB cache mode without flush
          - Flush page cache
          - Power off the main DUT
      - On backup DUT:
          - stop cache DRBD
          - set backup DUT as primary for core DRBD
          - deatch cache drive from standby cache instance
          - activate standby cache instance directly on the cache RAID drive
          - mount file system located on CAS exported object
          - Calculate checksum of fio test file(s)
       - Verify checksums from the previous steps are equal
       - Power on the main DUT
    """
    pass
