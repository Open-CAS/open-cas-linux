#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import unittest.mock as mock
import stat

import helpers as h
import opencas


@pytest.mark.parametrize(
    "line",
    [
        "",
        " ",
        "#",
        "                      #                      ",
        (
            "TG9yZW0gaXBzdW0gZG9sb3Igc2l0IGFtZXQsIGNvbnNlY3RldHVyIGFkaXBpc2Npbmcg"
            "ZWxpdCwgc2VkIGRvIGVpdXNtb2QgdGVtcG9yIGluY2lkaWR1bnQgdXQgbGFib3JlI"
            "GV0IGRvbG9yZSBtYWduYSBhbGlxdWEu"
        ),
        " # ? } { ! ",
        "1 1 /dev/not_a_real_device /dev/sdb",
        "1 2    1 /dev/not_a_real_device ",
        "1 2 1 /dev/not_a_real_device dinosaur=velociraptor",
    ],
)
@mock.patch("opencas.cas_config.core_config.validate_config")
def test_core_config_from_line_parsing_checks_01(mock_validate, line):
    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "1 1 /dev/not_a_real_device",
        "1     1 /dev/not_a_real_device ",
        "1  1   /dev/not_a_real_device  lazy_startup=true",
        "1  1   /dev/not_a_real_device  lazy_startup=false",
        "1  1   /dev/not_a_real_device  lazy_startup=False",
        "1  1   /dev/not_a_real_device  lazy_startup=True",
    ],
)
def test_core_config_from_line_parsing_checks_02(line):
    opencas.cas_config.core_config.from_line(line, allow_incomplete=True)


@pytest.mark.parametrize(
    "line",
    [
        "1 1 /dev/not_a_real_device dinosaur=velociraptor",
        "1 1 /dev/not_a_real_device lazy_startup=maybe",
        "1 1 /dev/not_a_real_device lazy_saturday=definitely",
        "1 1 /dev/not_a_real_device 00000=345",
        "1 1 /dev/not_a_real_device eval(38+4)",
    ],
)
def test_core_config_from_line_parsing_checks_params_01(line):
    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line(line, allow_incomplete=True)


@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_core_config_from_line_device_is_directory(mock_stat, mock_path_exists):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/home/user/stuff"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFDIR)

    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line("1    1   /home/user/stuff")


@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_core_config_from_line_device_not_present(mock_stat, mock_path_exists):
    mock_path_exists.side_effect = h.get_mock_os_exists([])
    mock_stat.side_effect = ValueError()

    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line("1    1   /dev/not_a_real_device")


def test_core_config_from_line_recursive_multilevel():
    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line("1    1   /dev/cas1-1")


def test_core_config_from_line_multilevel():
    opencas.cas_config.core_config.from_line("1    1   /dev/cas2-1")


@mock.patch("opencas.cas_config.check_block_device")
def test_core_config_from_line_allow_incomplete(mock_check_block,):
    opencas.cas_config.core_config.from_line(
        "1    1   /dev/not_a_real_device", allow_incomplete=True
    )

    assert not mock_check_block.called


@pytest.mark.parametrize(
    "cache_id,core_id",
    [
        ("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "bbbbbbb"),
        ("lizard", "chicken"),
        ("0", "0"),
        ("0", "100"),
        ("0", "-1"),
        ("-1", "0"),
        ("-1", "1"),
        ("-1", "-1"),
        ("16385", "4095"),
        ("16384", "4096"),
        ("0", "0"),
        ("1", "-1"),
    ],
)
@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_core_config_from_line_cache_id_validation_01(
    mock_stat, mock_path_exists, cache_id, core_id
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/not_a_real_device"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)

    line = "{0}   {1}   /dev/not_a_real_device".format(cache_id, core_id)

    with pytest.raises(ValueError):
        opencas.cas_config.core_config.from_line(line)


@pytest.mark.parametrize(
    "cache_id,core_id", [("16384", "4095"), ("1", "0"), ("1", "10")]
)
@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_core_config_from_line_cache_id_validation_02(
    mock_stat, mock_path_exists, cache_id, core_id
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/not_a_real_device"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)

    line = "{0}   {1}   /dev/not_a_real_device".format(cache_id, core_id)

    opencas.cas_config.core_config.from_line(line)


@pytest.mark.parametrize(
    "cache_id,core_id,device",
    [
        ("1", "1", "/dev/not_a_real_device"),
        ("16384", "4095", "/dev/not_a_real_device"),
        ("16384", "0", "/dev/nvme0n1p"),
        ("100", "5", "/dev/dm-10"),
    ],
)
@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_core_config_from_line_cache_id_validation(
    mock_stat, mock_path_exists, cache_id, core_id, device
):
    mock_path_exists.side_effect = h.get_mock_os_exists([device])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)

    core_reference = opencas.cas_config.core_config(
        cache_id=cache_id, core_id=core_id, path=device
    )

    core_reference.validate_config()

    core_after = opencas.cas_config.core_config.from_line(core_reference.to_line())
    assert core_after.cache_id == core_reference.cache_id
    assert core_after.core_id == core_reference.core_id
    assert core_after.device == core_reference.device
