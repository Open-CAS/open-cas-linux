#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from unittest.mock import patch, Mock
import time
import subprocess

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
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_cores_didnt_start_01(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    Single core in config, no devices in runtime config.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[opencas.cas_config.core_config(42, 13, "/dev/dummy")],
    )

    time_start = time.time()

    result = opencas.wait_for_startup(timeout=3, interval=1)

    time_stop = time.time()

    assert len(result) == 1, "didn't return single uninitialized core"
    assert result[0].cache_id == 42 and result[0].core_id == 13 and result[0].device == "/dev/dummy"
    assert 2.5 < time_stop - time_start < 3.5, "didn't wait the right amount of time"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_cores_didnt_start_02(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    Single device in config, one device in runtime config, but not the configured core
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[opencas.cas_config.core_config(1, 1, "/dev/dummy")],
    )

    mock_list.return_value = [
        {
            "type": "cache",
            "id": "1",
            "disk": "/dev/dummy_cache",
            "status": "Standby",
            "write policy": "wt",
            "device": "-",
        }
    ]

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 1, "didn't return uninitialized core"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_cores_didnt_start_03(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    The device waited for is in core pool.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[opencas.cas_config.core_config(1, 1, "/dev/dummy")],
    )

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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 0


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_cores_didnt_start_04(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and waits for given time

    The device waited for is not present, but its cache device is already started.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[opencas.cas_config.core_config(1, 1, "/dev/dummy")],
    )

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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 1, "didn't return uninitialized core"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_cores_didnt_start_05(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores

    Two devices configured, both not present.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(4, 44, "/dev/dosko"),
        ],
    )

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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 2, "didn't return uninitialized cores"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.start_cache")
def test_cas_settle_caches_didnt_start_01(
    mock_start, mock_exists, mock_run, mock_list, mock_config
):
    """
    Check if properly returns uninitialized caches and waits for given time

    Single cache in config, no devices in runtime config.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        cores=[],
        caches={
            42: opencas.cas_config.cache_config(
                42, "/dev/dummy", "wt", target_failover_state="standby"
            )
        },
    )

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 1, "didn't return single uninitialized cache"
    assert result[0].cache_id == 42 and result[0].device == "/dev/dummy"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.start_cache")
def test_cas_settle_caches_didnt_start_02(
    mock_start, mock_exists, mock_run, mock_list, mock_config
):
    """
    Check if properly returns uninitialized cache and waits for given time

    Single device in config, one device in runtime config, but not the configured cache
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        cores=[],
        caches={1: opencas.cas_config.cache_config(1, "/dev/dummy", "wt")},
    )

    mock_list.return_value = [
        {
            "type": "cache",
            "id": "3",
            "disk": "/dev/dummy_cache",
            "status": "Active",
            "write policy": "wt",
            "device": "-",
        }
    ]

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 1, "didn't return uninitialized cache"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.start_cache")
def test_cas_settle_caches_didnt_start_03(
    mock_start, mock_exists, mock_run, mock_list, mock_config
):
    """
    Check if properly returns uninitialized caches

    Two devices configured, both not present.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        cores=[],
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/dummy", "wt"),
            4: opencas.cas_config.cache_config(4, "/dev/dosko", "wo"),
        },
    )

    mock_list.return_value = [
        {
            "type": "cache",
            "id": "8",
            "disk": "/dev/dummy_cache",
            "status": "Incomplete",
            "write policy": "wt",
            "device": "-",
        },
        {
            "type": "core",
            "id": "1",
            "disk": "/dev/yes",
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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 2, "didn't return uninitialized caches"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_core_started_01(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, one present, one not present.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(4, 44, "/dev/dosko"),
        ],
    )

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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 1, "didn't return uninitialized core"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_core_started_02(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, both present and added.
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(4, 44, "/dev/dosko"),
        ],
    )

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

    result = opencas.wait_for_startup(timeout=0, interval=0)

    assert len(result) == 0, "no cores should remain uninitialized"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
def test_cas_settle_core_started_03(mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if properly returns uninitialized cores and doesn't return initialized ones

    Two devices configured, simulate them gradually showing up with each call to
    get_caches_list()
    """

    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={},
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko"),
        ],
    )

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

    result = opencas.wait_for_startup(timeout=1, interval=0.01)

    assert len(result) == 0, "no cores should remain uninitialized"


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_01(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is not attempted while waiting for startup if paths to
    devices don't exist.

    """
    mock_config.return_value = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt"),
            2: opencas.cas_config.cache_config(2, "/dev/chemtrails", "wo"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko"),
        ],
    )

    mock_exists.return_value = False

    result = opencas.wait_for_startup(timeout=0, interval=0)

    mock_add.assert_not_called()
    mock_start.assert_not_called()
    mock_run.assert_called_with(["udevadm", "settle"])


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_02(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is attempted while waiting for startup.

    """
    config = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt"),
            2: opencas.cas_config.cache_config(2, "/dev/wartortle", "wo"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko"),
        ],
    )

    mock_config.return_value = config

    mock_exists.return_value = True

    result = opencas.wait_for_startup(timeout=0, interval=0)

    mock_start.assert_any_call(config.caches[1], load=True)
    mock_start.assert_any_call(config.caches[2], load=True)
    mock_add.assert_any_call(config.cores[0], try_add=True)
    mock_add.assert_any_call(config.cores[1], try_add=True)
    mock_run.assert_called_with(["udevadm", "settle"])


def _exists_mock(timeout):
    def mock(path):
        if time.time() > timeout:
            return True
        else:
            return False

    return mock


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_03(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is not attempted while waiting for startup if paths to
    devices show up after expiring waiting timeout.

    """
    config = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt"),
            2: opencas.cas_config.cache_config(2, "/dev/aerodactyl", "wo"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/dummy"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko"),
        ],
    )

    mock_config.return_value = config

    mock_exists.side_effect = _exists_mock(time.time() + 10)

    result = opencas.wait_for_startup(timeout=0.5, interval=0.1)

    mock_start.assert_not_called()
    mock_add.assert_not_called()
    mock_run.assert_called_with(["udevadm", "settle"])


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_04(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is attempted while waiting for startup if paths to
    devices show up after half of the waiting timeout expires.
    """
    config = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt"),
            2: opencas.cas_config.cache_config(2, "/dev/chemtrails", "wo"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/sandshrew"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko"),
        ],
    )

    mock_config.return_value = config

    mock_exists.side_effect = _exists_mock(time.time() + 1)

    result = opencas.wait_for_startup(timeout=2, interval=0.1)

    mock_start.assert_any_call(config.caches[1], load=True)
    mock_start.assert_any_call(config.caches[2], load=True)
    mock_add.assert_any_call(config.cores[0], try_add=True)
    mock_add.assert_any_call(config.cores[1], try_add=True)
    mock_run.assert_called_with(["udevadm", "settle"])


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_05(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is attempted while waiting for startup for lazy_startup
    devices once before returning.
    """
    config = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt", lazy_startup="true"),
            2: opencas.cas_config.cache_config(2, "/dev/chemtrails", "wo", lazy_startup="true"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/sandshrew", lazy_startup="true"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko", lazy_startup="true"),
        ],
    )

    mock_config.return_value = config

    mock_exists.return_value = True

    result = opencas.wait_for_startup(timeout=0.5, interval=0.1)

    mock_start.assert_any_call(config.caches[1], load=True)
    mock_start.assert_any_call(config.caches[2], load=True)
    assert mock_start.call_count == 2, "start cache was called more than once per device"
    mock_add.assert_any_call(config.cores[0], try_add=True)
    mock_add.assert_any_call(config.cores[1], try_add=True)
    assert mock_add.call_count == 2, "add core was called more than once per device"
    mock_run.assert_called_with(["udevadm", "settle"])


@patch("opencas.cas_config.from_file")
@patch("opencas.get_caches_list")
@patch("subprocess.run")
@patch("os.path.exists")
@patch("opencas.add_core")
@patch("opencas.start_cache")
def test_last_resort_add_06(mock_start, mock_add, mock_exists, mock_run, mock_list, mock_config):
    """
    Check if adding cores/starting caches is not attempted while waiting for startup for lazy
    startup devices if paths show up after half of the startup timeout expires.
    """
    config = Mock(
        spec_set=opencas.cas_config(),
        caches={
            1: opencas.cas_config.cache_config(1, "/dev/lizards", "wt", lazy_startup="true"),
            2: opencas.cas_config.cache_config(2, "/dev/chemtrails", "wo", lazy_startup="true"),
        },
        cores=[
            opencas.cas_config.core_config(1, 1, "/dev/sandshrew", lazy_startup="true"),
            opencas.cas_config.core_config(2, 1, "/dev/dosko", lazy_startup="true"),
        ],
    )

    mock_config.return_value = config

    mock_exists.side_effect = _exists_mock(time.time() + 1)

    result = opencas.wait_for_startup(timeout=2, interval=0.5)

    mock_start.assert_not_called()
    mock_add.assert_not_called()
    mock_run.assert_called_with(["udevadm", "settle"])


def assert_option_value(call, option, value):
    try:
        index = call.index(option)
    except ValueError as e:
        raise AssertionError(f"{option} not found in call ({call})") from e

    assert call[index + 1] == value


@pytest.mark.parametrize("failover", ["standby", "active"])
@pytest.mark.parametrize("force", [True, False])
@pytest.mark.parametrize("load", [True, False])
@patch("subprocess.run")
def test_start_cache(mock_run, load, force, failover):
    cache_config = opencas.cas_config.cache_config(
        1,
        "/dev/lizards",
        "wt",
        lazy_startup="true",
        cache_line_size="64",
        target_failover_state=failover,
    )
    mock_run.return_value = Mock(
        returncode=0,
        stderr="",
        stdout="",
    )

    opencas.start_cache(cache_config, load, force)

    casadm_call = mock_run.call_args[0][0]
    assert "/sbin/casadm" in casadm_call
    assert_option_value(casadm_call, "--cache-device", "/dev/lizards")

    if not load:
        assert_option_value(casadm_call, "--cache-id", "1")
        assert_option_value(casadm_call, "--cache-line-size", "64")
        if failover == "active":
            assert "--start-cache" in casadm_call
            assert_option_value(casadm_call, "--cache-mode", "wt")
        else:
            assert "--standby" in casadm_call
            assert "--init" in casadm_call
    else:
        assert "--load" in casadm_call
        assert "--cache-id" not in casadm_call
        assert "--cache-mode" not in casadm_call
        assert "--cache-line-size" not in casadm_call
