#
# Copyright(c) 2019-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import pytest
from unittest.mock import patch
import time

import opencas


@patch("opencas.cas_config.from_file")
def test_cas_settle_no_config(mock_config):
    """
    Check if raises exception when no config is found
    """

    mock_config.side_effect = ValueError

    with pytest.raises(Exception):
        opencas.wait_for_startup()


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_cores_didnt_start_01(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    Single core in config, no devices in runtime config.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(42, 13, "/dev/dummy")
    ]

    time_start = time.time()

    result = opencas.wait_for_startup(timeout=5, interval=1)

    time_stop = time.time()

    assert len(result) == 1, "didn't return single uninitialized core"
    assert (
        result[0].cache_id == 42
        and result[0].core_id == 13
        and result[0].device == "/dev/dummy"
    )
    assert 4.5 < time_stop - time_start < 5.5, "didn't wait the right amount of time"
    assert mock_list.call_count == 5


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_cores_didnt_start_02(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    Single device in config, one device in runtime config, but not the configured core
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy")
    ]

    mock_list.return_value = [
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Active",
            "write policy": "wt",
            "device": "-",
        }
    ]

    time_start = time.time()

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    time_stop = time.time()

    assert len(result) == 1, "didn't return uninitialized core"
    assert 0.5 < time_stop - time_start < 1.5, "didn't wait the right amount of time"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_cores_didnt_start_02(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    The device waited for is in core pool.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy")
    ]

    mock_list.return_value = [
        {
            "type": "core pool",
            "id": "-",
            "disk": "-",
            "status": "-",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "core",
            "id": "-",
            "disk": "/dev/dummy",
            "status": "Detached",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "cache",
            "id": "2",
            "disk": "/dev/dummy_cache",
            "status": "Running",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "42",
            "disk": "/dev/other_core",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas2-42",
        },
    ]

    time_start = time.time()

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    time_stop = time.time()

    assert len(result) == 1, "didn't return uninitialized core"
    assert 0.5 < time_stop - time_start < 1.5, "didn't wait the right amount of time"
    # Assert the call count is within some small range in case something freezes up for a second
    assert 9 <= mock_list.call_count <= 11


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_cores_didnt_start_03(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    The device waited for is not present, but its cache device is already started.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy")
    ]

    mock_list.return_value = [
        {
            "type": "core pool",
            "id": "-",
            "disk": "-",
            "status": "-",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "core",
            "id": "-",
            "disk": "/dev/other_core",
            "status": "Detached",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Incomplete",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "42",
            "disk": "/dev/dummy",
            "status": "Inactive",
            "write policy": "-",
            "device": "/dev/cas1-42",
        },
        {
            "type": "cache",
            "id": "2",
            "disk": "/dev/dummy_cache2",
            "status": "Running",
            "write policy": "wb",
            "device": "-",
        },
        {
            "type": "core",
            "id": "3",
            "disk": "/dev/dummy2",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-42",
        },
    ]

    time_start = time.time()

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    time_stop = time.time()

    assert len(result) == 1, "didn't return uninitialized core"
    assert 0.5 < time_stop - time_start < 1.5, "didn't wait the right amount of time"
    # Assert the call count is within some small range in case something freezes up for a second
    assert 9 <= mock_list.call_count <= 11


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_cores_didnt_start_04(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores

    Two devices configured, both not present.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy"),
        opencas.cas_config.core_config(4, 44, "/dev/dosko"),
    ]

    mock_list.return_value = [
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Incomplete",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "1",
            "disk": "/dev/dummy",
            "status": "Inactive",
            "write policy": "-",
            "device": "/dev/cas1-1",
        },
        {
            "type": "core",
            "id": "2",
            "disk": "/dev/dummy3",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-2",
        },
        {
            "type": "cache",
            "id": "2",
            "disk": "/dev/dummy_cache2",
            "status": "Running",
            "write policy": "wb",
            "device": "-",
        },
        {
            "type": "core",
            "id": "3",
            "disk": "/dev/dummy2",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas2-3",
        },
    ]

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    assert len(result) == 2, "didn't return uninitialized cores"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_core_started_01(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, one present, one not present.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy"),
        opencas.cas_config.core_config(4, 44, "/dev/dosko"),
    ]

    mock_list.return_value = [
        {
            "type": "core pool",
            "id": "-",
            "disk": "-",
            "status": "-",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "core",
            "id": "-",
            "disk": "/dev/other_core",
            "status": "Detached",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Incomplete",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "1",
            "disk": "/dev/dummy",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-1",
        },
        {
            "type": "cache",
            "id": "2",
            "disk": "/dev/dummy_cache2",
            "status": "Running",
            "write policy": "wb",
            "device": "-",
        },
        {
            "type": "core",
            "id": "3",
            "disk": "/dev/dummy2",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-42",
        },
    ]

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    assert len(result) == 1, "didn't return uninitialized core"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_core_started_02(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, both present and added.
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy"),
        opencas.cas_config.core_config(4, 44, "/dev/dosko"),
    ]

    mock_list.return_value = [
        {
            "type": "core pool",
            "id": "-",
            "disk": "-",
            "status": "-",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "core",
            "id": "-",
            "disk": "/dev/other_core",
            "status": "Detached",
            "write policy": "-",
            "device": "-",
        },
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Running",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "1",
            "disk": "/dev/dummy",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-42",
        },
        {
            "type": "cache",
            "id": "2",
            "disk": "/dev/dummy_cache2",
            "status": "Running",
            "write policy": "wb",
            "device": "-",
        },
        {
            "type": "core",
            "id": "3",
            "disk": "/dev/dummy2",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas1-42",
        },
        {
            "type": "cache",
            "id": "4",
            "disk": "/dev/dummy_cache4",
            "status": "Running",
            "write policy": "wb",
            "device": "-",
        },
        {
            "type": "core",
            "id": "44",
            "disk": "/dev/dosko",
            "status": "Active",
            "write policy": "-",
            "device": "/dev/cas4-44",
        },
    ]

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    assert len(result) == 0, "no cores should remain uninitialized"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
def test_cas_settle_core_started_03(mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, simulate them gradually showing up with each call to
    get_caches_list()
    """

    mock_config.return_value.get_startup_cores.return_value = [
        opencas.cas_config.core_config(1, 1, "/dev/dummy"),
        opencas.cas_config.core_config(2, 1, "/dev/dosko"),
    ]

    mock_list.side_effect = [
        [],
        [
            {
                "type": "cache",
                "id": "2",
                "disk": "/dev/dummy_cache4",
                "status": "Incomplete",
                "write policy": "wb",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dosko",
                "status": "Inactive",
                "write policy": "-",
                "device": "/dev/cas2-1",
            },
        ],
        [
            {
                "type": "cache",
                "id": "2",
                "disk": "/dev/dummy_cache4",
                "status": "Incomplete",
                "write policy": "wb",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dosko",
                "status": "Inactive",
                "write policy": "-",
                "device": "/dev/cas2-1",
            },
            {
                "type": "cache",
                "id": "1",
                "disk": "/dev/dummy_cache",
                "status": "Incomplete",
                "write policy": "wt",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dummy",
                "status": "Active",
                "write policy": "-",
                "device": "/dev/cas1-1",
            },
        ],
        [
            {
                "type": "cache",
                "id": "2",
                "disk": "/dev/dummy_cache4",
                "status": "Running",
                "write policy": "wb",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dosko",
                "status": "Active",
                "write policy": "-",
                "device": "/dev/cas2-1",
            },
            {
                "type": "cache",
                "id": "1",
                "disk": "/dev/dummy_cache",
                "status": "Incomplete",
                "write policy": "wt",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dummy",
                "status": "Inactive",
                "write policy": "-",
                "device": "/dev/cas1-1",
            },
        ],
        [
            {
                "type": "cache",
                "id": "2",
                "disk": "/dev/dummy_cache4",
                "status": "Running",
                "write policy": "wb",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dosko",
                "status": "Active",
                "write policy": "-",
                "device": "/dev/cas2-1",
            },
            {
                "type": "cache",
                "id": "1",
                "disk": "/dev/dummy_cache",
                "status": "Running",
                "write policy": "wt",
                "device": "-",
            },
            {
                "type": "core",
                "id": "1",
                "disk": "/dev/dummy",
                "status": "Active",
                "write policy": "-",
                "device": "/dev/cas1-1",
            },
        ],
    ]

    result = opencas.wait_for_startup(timeout=1, interval=0.1)

    assert len(result) == 0, "no cores should remain uninitialized"
