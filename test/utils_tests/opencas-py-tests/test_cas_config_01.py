#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from unittest.mock import patch, mock_open
from textwrap import dedent
import helpers as h

import opencas


@patch("builtins.open", new_callable=mock_open)
def test_cas_config_from_file_exception(mock_file):
    mock_file.raises = ValueError()

    with pytest.raises(Exception):
        opencas.cas_config.from_file("/dummy/file.conf")

    mock_file.assert_called_once_with("/dummy/file.conf", "r")


@patch(
    "builtins.open",
    new_callable=h.MockConfigFile,
    buffer="""
            [caches]
            1   /dev/nvme0n1 WT
            [cores]
            1   1   /dev/sdc
            """,
)
def test_cas_config_from_file_no_vertag(mock_file):
    with pytest.raises(ValueError):
        opencas.cas_config.from_file("/dummy/file.conf")


@patch(
    "builtins.open",
    new_callable=h.MockConfigFile,
    buffer="""
            version=03.08.00
            #[caches]
            #1   /dev/nvme0n1 WT
            #[cores]
            #1   1   /dev/sdc
            """,
)
@patch("opencas.cas_config.core_config.from_line")
@patch("opencas.cas_config.cache_config.from_line")
@patch("opencas.cas_config.insert_core")
@patch("opencas.cas_config.insert_cache")
def test_cas_config_from_file_comments_only(
    mock_insert_cache,
    mock_insert_core,
    mock_cache_from_line,
    mock_core_from_line,
    mock_file,
):

    config = opencas.cas_config.from_file("/dummy/file.conf")

    mock_cache_from_line.assert_not_called()
    mock_core_from_line.assert_not_called()
    mock_insert_cache.assert_not_called()
    mock_insert_core.assert_not_called()

    assert config.is_empty()


ConflictingConfigException = opencas.cas_config.ConflictingConfigException
AlreadyConfiguredException = opencas.cas_config.AlreadyConfiguredException


@pytest.mark.parametrize(
    "caches_config,cores_config,exception",
    [
        (
            [
                "1  /dev/dummy0n1    WT",
                "2  /dev/dummy0n1    WT",
                "3  /dev/dummy0n1    WT",
            ],
            ["1  1   /dev/dummyc"],
            ConflictingConfigException,
        ),
        (
            ["1  /dev/dummyc    WT"],
            ["1  1   /dev/dummyc"],
            ConflictingConfigException,
        ),
        (
            ["1  /dev/dummya    WT", "1  /dev/dummy0n1    WT"],
            ["1  1   /dev/dummyc"],
            ConflictingConfigException,
        ),
        (
            ["1  /dev/dummya    WT", "1  /dev/dummya    WT"],
            ["1  1   /dev/dummyc"],
            AlreadyConfiguredException,
        ),
        (
            ["1  /dev/dummya    WT"],
            ["1  1   /dev/dummyc", "1  1   /dev/dummyc"],
            AlreadyConfiguredException,
        ),
        (
            ["2  /dev/dummya    WT"],
            ["1  1   /dev/dummyc", "2  1   /dev/dummyb"],
            KeyError,
        ),
        (
            ["1  /dev/dummya    WT", "2  /dev/dummy0n1    WT"],
            ["1  1   /dev/dummyc", "2  1   /dev/dummyc"],
            ConflictingConfigException,
        ),
    ],
)
@patch("builtins.open", new_callable=h.MockConfigFile)
@patch("opencas.cas_config.cache_config.validate_config")
@patch("opencas.cas_config.core_config.validate_config")
def test_cas_config_from_file_inconsistent_configs(
    mock_validate_core,
    mock_validate_cache,
    mock_file,
    caches_config,
    cores_config,
    exception,
):

    mock_file.set_contents(
        dedent(
            """
            version=3.8.0
            [caches]
            {0}
            [cores]
            {1}
            """
        ).format("\n".join(caches_config), "\n".join(cores_config))
    )

    with pytest.raises(exception):
        opencas.cas_config.from_file("/dummy/file.conf")


@patch(
    "builtins.open",
    new_callable=h.MockConfigFile,
    buffer="""
            version=3.8.0
            [caches]
            1   /dev/dummy0n1 WT
            [cores]
            1   1   /dev/dummyc
            """,
)
@patch("opencas.cas_config.cache_config.validate_config")
@patch("opencas.cas_config.core_config.validate_config")
def test_cas_config_is_empty_non_empty(
    mock_validate_core, mock_validate_cache, mock_file
):

    config = opencas.cas_config.from_file("/dummy/file.conf")

    assert not config.is_empty()


def test_cas_config_double_add_cache():
    config = opencas.cas_config()

    cache = opencas.cas_config.cache_config(1, "/dev/dummy", "WT")
    config.insert_cache(cache)

    with pytest.raises(AlreadyConfiguredException):
        config.insert_cache(cache)


def test_cas_config_double_add_core():
    config = opencas.cas_config()
    cache = opencas.cas_config.cache_config(1, "/dev/dummy1", "WT")
    config.insert_cache(cache)

    core = opencas.cas_config.core_config(1, 1, "/dev/dummy")
    config.insert_core(core)

    with pytest.raises(AlreadyConfiguredException):
        config.insert_core(core)


def test_cas_config_insert_core_no_cache():
    config = opencas.cas_config()

    core = opencas.cas_config.core_config(1, 1, "/dev/dummy")

    with pytest.raises(KeyError):
        config.insert_core(core)


@patch("os.path.realpath")
def test_cas_config_add_same_cache_symlinked_01(mock_realpath):
    mock_realpath.side_effect = (
        lambda x: "/dev/dummy1" if x == "/dev/dummy_link" else x
    )

    config = opencas.cas_config()
    cache = opencas.cas_config.cache_config(1, "/dev/dummy1", "WT")
    config.insert_cache(cache)

    cache_symlinked = opencas.cas_config.cache_config(
        2, "/dev/dummy_link", "WB"
    )

    with pytest.raises(ConflictingConfigException):
        config.insert_cache(cache_symlinked)


@patch("os.path.realpath")
def test_cas_config_add_same_cache_symlinked_02(mock_realpath):
    mock_realpath.side_effect = (
        lambda x: "/dev/dummy1" if x == "/dev/dummy_link" else x
    )

    config = opencas.cas_config()
    cache = opencas.cas_config.cache_config(1, "/dev/dummy1", "WT")
    config.insert_cache(cache)

    cache_symlinked = opencas.cas_config.cache_config(
        1, "/dev/dummy_link", "WB"
    )

    with pytest.raises(AlreadyConfiguredException):
        config.insert_cache(cache_symlinked)


@patch("os.path.realpath")
def test_cas_config_add_same_core_symlinked_01(mock_realpath):
    mock_realpath.side_effect = (
        lambda x: "/dev/dummy1" if x == "/dev/dummy_link" else x
    )

    config = opencas.cas_config()
    config.insert_cache(
        opencas.cas_config.cache_config(1, "/dev/dummy_cache", "WB")
    )
    core = opencas.cas_config.core_config(1, 1, "/dev/dummy1")
    config.insert_core(core)

    core_symlinked = opencas.cas_config.core_config(1, 2, "/dev/dummy_link")

    with pytest.raises(ConflictingConfigException):
        config.insert_core(core_symlinked)


@patch("os.path.realpath")
def test_cas_config_add_same_core_symlinked_02(mock_realpath):
    mock_realpath.side_effect = (
        lambda x: "/dev/dummy1" if x == "/dev/dummy_link" else x
    )

    config = opencas.cas_config()
    config.insert_cache(
        opencas.cas_config.cache_config(1, "/dev/dummy_cache", "WB")
    )
    core = opencas.cas_config.core_config(1, 1, "/dev/dummy1")
    config.insert_core(core)

    core_symlinked = opencas.cas_config.core_config(1, 1, "/dev/dummy_link")

    with pytest.raises(AlreadyConfiguredException):
        config.insert_core(core_symlinked)


@patch("os.path.realpath")
@patch("os.listdir")
def test_cas_config_get_by_id_path_not_found(mock_listdir, mock_realpath):
    mock_listdir.return_value = [
        "wwn-1337deadbeef-x0x0",
        "wwn-1337deadbeef-x0x0-part1",
        "nvme-INTEL_SSDAAAABBBBBCCC_0984547ASDDJHHHFH",
    ]
    mock_realpath.side_effect = lambda x: x

    with pytest.raises(ValueError):
        path = opencas.cas_config.get_by_id_path("/dev/dummy1")


@pytest.mark.parametrize(
    "caches_config,cores_config",
    [
        (
            [
                "1  /dev/dummy0n1    WT",
                "2  /dev/dummy0n2    WT",
                "3  /dev/dummy0n3    WT",
            ],
            ["1  1   /dev/dummyc"],
        ),
        ([], []),
        (
            [
                "1  /dev/dummy0n1    WT",
                "2  /dev/dummy0n2    WT",
                "3  /dev/dummy0n3    WT",
            ],
            [
                "1  1   /dev/dummyc1",
                "2  200   /dev/dummyc2",
                "3  100   /dev/dummyc3",
            ],
        ),
        (
            [
                "1  /dev/dummy0n1    WT cleaning_policy=acp,lazy_startup=true",
                "2  /dev/dummy0n2    pt ioclass_file=mango.csv",
                "3  /dev/dummy0n3    WA cache_line_size=16",
                ("4  /dev/dummyc    wb cache_line_size=16,"
                    "ioclass_file=mango.csv,cleaning_policy=nop,target_failover_state=standby"),
            ],
            [],
        ),
        (
            [
                "1  /dev/dummy0n1    WT cleaning_policy=acp",
            ],
            [
                "1  1   /dev/dummy1 lazy_startup=true"
            ],
        ),
    ],
)
@patch("builtins.open", new_callable=h.MockConfigFile)
@patch("opencas.cas_config.cache_config.validate_config")
@patch("opencas.cas_config.core_config.validate_config")
def test_cas_config_from_file_to_file(
    mock_validate_core,
    mock_validate_cache,
    mock_file,
    caches_config,
    cores_config,
):
    """
    1. Read config from mocked file with parametrized caches and cores section
    2. Serialize config back to mocked file
    3. Check if serialized file is proper config file and the same content-wise
       as the initial file. Specifically check:
           * Version tag is present in first line
           * There is only one of each [caches] and [cores] sections marking
           * [cores] section comes after [caches]
           * sets of caches and cores are equal before and after test
    """

    mock_file.set_contents(
        dedent(
            """
            version=3.8.0
            [caches]
            {0}
            [cores]
            {1}
            """
        ).format("\n".join(caches_config), "\n".join(cores_config))
    )

    config = opencas.cas_config.from_file("/dummy/file.conf")

    config.write("/dummy/file.conf")

    f = mock_file("/dummy/file.conf", "r")
    contents_hashed = h.get_hashed_config_list(f)

    assert contents_hashed[0] == "version=3.8.0"
    assert contents_hashed.count("[caches]") == 1
    assert contents_hashed.count("[cores]") == 1

    caches_index = contents_hashed.index("[caches]")
    cores_index = contents_hashed.index("[cores]")

    assert cores_index > caches_index

    caches_hashed = h.get_hashed_config_list(caches_config)
    cores_hashed = h.get_hashed_config_list(cores_config)

    assert set(caches_hashed) == set(
        contents_hashed[caches_index + 1 : cores_index]
    )
    assert set(cores_hashed) == set(contents_hashed[cores_index + 1 :])


@pytest.mark.parametrize(
    "caches_config,cores_config",
    [
        (
            [
                "1  /dev/dummy0n1    WT",
                "2  /dev/dummy0n2    WT",
                "3  /dev/dummy0n3    WT",
            ],
            ["1  1   /dev/dummyc"],
        ),
        ([], []),
        (
            [
                "1  /dev/dummy0n1    WT",
                "2  /dev/dummy0n2    WT",
                "3  /dev/dummy0n3    WT",
            ],
            [
                "1  1   /dev/dummyc1",
                "2  200   /dev/dummyc2",
                "3  100   /dev/dummyc3",
            ],
        ),
        (
            [
                "1  /dev/dummy0n1    WT cleaning_policy=acp",
                "2  /dev/dummy0n2    pt ioclass_file=mango.csv",
                "3  /dev/dummy0n3    WA cache_line_size=16",
                ("4  /dev/dummyc    wb cache_line_size=16,"
                    "ioclass_file=mango.csv,cleaning_policy=nop"),
            ],
            [],
        ),
    ],
)
@patch("builtins.open", new_callable=h.MockConfigFile)
@patch("opencas.cas_config.cache_config.validate_config")
@patch("opencas.cas_config.core_config.validate_config")
def test_cas_config_from_file_insert_cache_insert_core_to_file(
    mock_validate_core,
    mock_validate_cache,
    mock_file,
    caches_config,
    cores_config,
):
    """
    1. Read config from mocked file with parametrized caches and cores section
    2. Add one core and one cache to config
    3. Serialize config back to mocked file
    4. Compare that config file after serialization is same content-wise with
       initial + added core and cache
    """

    mock_file.set_contents(
        dedent(
            """
            version=3.8.0
            [caches]
            {0}
            [cores]
            {1}
            """
        ).format("\n".join(caches_config), "\n".join(cores_config))
    )

    config = opencas.cas_config.from_file("/dummy/file.conf")

    config.insert_cache(opencas.cas_config.cache_config(5, "/dev/mango", "WT"))
    config.insert_core(opencas.cas_config.core_config(5, 1, "/dev/mango_core"))

    config.write("/dummy/file.conf")

    f = mock_file("/dummy/file.conf", "r")
    contents_hashed = h.get_hashed_config_list(f)

    caches_index = contents_hashed.index("[caches]")
    cores_index = contents_hashed.index("[cores]")

    caches_hashed = h.get_hashed_config_list(caches_config)
    cores_hashed = h.get_hashed_config_list(cores_config)

    assert set(contents_hashed[caches_index + 1 : cores_index]) - set(
        caches_hashed
    ) == set(["5/dev/mangowt"])
    assert set(contents_hashed[cores_index + 1 :]) - set(cores_hashed) == set(
        ["51/dev/mango_core"]
    )
