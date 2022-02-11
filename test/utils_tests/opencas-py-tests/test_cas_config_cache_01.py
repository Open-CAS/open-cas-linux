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
        "1 /dev/nvme0n1 WT 1 2 3",
        "1 /dev/nvme0n1 WT   ioclass_file=ioclass.csv ,cache_line_size=4",
    ],
)
@mock.patch("opencas.cas_config.cache_config.validate_config")
def test_cache_config_from_line_parsing_checks_01(mock_validate, line):
    with pytest.raises(ValueError):
        opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "1 /dev/nvme0n1 WT",
        "1 /dev/nvme0n1 WT   ioclass_file=ioclass.csv,cache_line_size=4",
    ],
)
@mock.patch("opencas.cas_config.cache_config.validate_config")
def test_cache_config_from_line_parsing_checks_02(mock_validate, line):
    opencas.cas_config.cache_config.from_line(line)


@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_cache_config_from_line_device_is_directory(mock_stat, mock_path_exists):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/home/user/catpictures"]
    )
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFDIR)

    with pytest.raises(ValueError, match="is not block device"):
        opencas.cas_config.cache_config.from_line(
            "1    /home/user/catpictures  WT"
        )


@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_cache_config_from_line_device_not_present(mock_stat, mock_path_exists):
    mock_path_exists.side_effect = h.get_mock_os_exists([])
    mock_stat.side_effect = OSError()

    with pytest.raises(ValueError, match="not found"):
        opencas.cas_config.cache_config.from_line("1    /dev/nvme0n1    WT")


@mock.patch("os.path.exists")
@mock.patch("os.stat")
@mock.patch("subprocess.run")
def test_cache_config_from_line_device_with_partitions(
    mock_run, mock_stat, mock_path_exists
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/sda"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)
    mock_run.return_value = h.get_process_mock(0, "sda\nsda1\nsda2", "")

    with pytest.raises(ValueError, match="Partitions"):
        opencas.cas_config.cache_config.from_line("1    /dev/sda    WT")


@mock.patch("os.path.exists")
@mock.patch("os.stat")
@mock.patch("subprocess.run")
def test_cache_config_validate_device_with_partitions(
    mock_run, mock_stat, mock_path_exists
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/sda"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)
    mock_run.return_value = h.get_process_mock(0, "sda\nsda1\nsda2", "")

    cache = opencas.cas_config.cache_config(
        cache_id="1", device="/dev/sda", cache_mode="WT"
    )

    with pytest.raises(ValueError, match="Partitions"):
        cache.validate_config(False)


@mock.patch("os.path.exists")
@mock.patch("os.stat")
@mock.patch("subprocess.run")
def test_cache_config_validate_force_device_with_partitions(
    mock_run, mock_stat, mock_path_exists
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/sda"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)
    mock_run.return_value = h.get_process_mock(0, "sda\nsda1\nsda2", "")

    cache = opencas.cas_config.cache_config(
        cache_id="1", device="/dev/sda", cache_mode="WT"
    )

    cache.validate_config(True)


@mock.patch("os.path.exists")
@mock.patch("os.stat")
@mock.patch("subprocess.run")
def test_cache_config_from_line_device_without_partitions(
    mock_run, mock_stat, mock_path_exists
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/sda"])
    mock_stat.return_value = mock.Mock(st_mode=stat.S_IFBLK)
    mock_run.return_value = h.get_process_mock(0, "sda\n", "")

    opencas.cas_config.cache_config.from_line("1    /dev/sda    WT")


@pytest.mark.parametrize("device", ["/dev/cas1-1", "/dev/cas1-300"])
@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_cache_config_from_line_recursive_multilevel(
    mock_stat, mock_path_exists, device
):
    mock_path_exists.side_effect = h.get_mock_os_exists([])
    mock_stat.raises = OSError()

    with pytest.raises(ValueError):
        opencas.cas_config.cache_config.from_line("1    {0}    WT".format(device))


@mock.patch("os.path.exists")
@mock.patch("os.stat")
def test_cache_config_from_line_multilevel(mock_stat, mock_path_exists):
    mock_path_exists.side_effect = h.get_mock_os_exists([])
    mock_stat.raises = OSError()

    opencas.cas_config.cache_config.from_line("2    /dev/cas1-1    WT")


@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_allow_incomplete(mock_check_block,):
    opencas.cas_config.cache_config.from_line(
        "1    /dev/sda    WT", allow_incomplete=True
    )

    assert not mock_check_block.called


@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_missing_ioclass_file(
    mock_check_block, mock_path_exists
):
    mock_path_exists.side_effect = h.get_mock_os_exists(["/dev/nvme0n1"])

    with pytest.raises(ValueError):
        opencas.cas_config.cache_config.from_line(
            (
                "11 /dev/nvme0n1 WT   ioclass_file=ioclass.csv,"
                "cleaning_policy=nop,cache_line_size=4"
            )
        )


@pytest.mark.parametrize(
    "params",
    [
        "ioclass_file=",
        "ioclass_file=asdf",
        "ioclass_file=ioclass.csv,ioclass_file=ioclass.csv",
        "cleaning_policy=nop,cleaning_policy=acp",
        "cleaning_policy=",
        "clining_polisi=nop",
        "cleaning_policy=INVALID",
        "ioclass_file=ioclass.csv, cleaning_policy=nop",
        "ioclas_file=ioclass.csv",
        "cache_line_size=4,cache_line_size=8",
        "cache_line_size=",
        "cache_line_size=0",
        "cache_line_size=4k",
        "cache_line_size=4kb",
        "cache_line_size=256",
        "cache_line_size=-1",
        "cache_line_size=four",
        "cache_line_size=128",
        "cach_lin_siz=4",
        "promotion_policy=111111",
        "promotion_policy=",
        "promotion_policy=dinosaurs",
        "promotion_policy=Robert'); DROP TABLE Students;--",
        "promotion_policy=awlays",
        "promotion_policy=nnhit",
        "demolition_policy=nhit",
        "lazy_startup=yes",
        "lazy_startup=absolutely",
        "hasty_startup=true",
        "target_failover_state=no",
        "target_failover_state=maybe",
        "target_failrover_state=standby",
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_parameter_validation_01(
    mock_check_block, mock_device_empty, mock_path_exists, params
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "1   /dev/sda    WT  {0}".format(params)

    with pytest.raises(ValueError, match="[Ii]nvalid"):
        opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "params",
    [
        "ioclass_file=ioclass.csv",
        "cleaning_policy=acp",
        "cleaning_policy=nop",
        "cleaning_policy=alru",
        "cleaning_policy=AlRu",
        "ioclass_file=ioclass.csv,cleaning_policy=nop",
        "cache_line_size=4",
        "cache_line_size=8",
        "cache_line_size=16",
        "cache_line_size=32",
        "cache_line_size=64",
        "cache_line_size=4,cleaning_policy=nop",
        "ioclass_file=ioclass.csv,cache_line_size=4,cleaning_policy=nop",
        "promotion_policy=nhit",
        "promotion_policy=always",
        "target_failover_state=standby",
        "target_failover_state=active",
        "lazy_startup=true",
        "lazy_startup=false",
        ("ioclass_file=ioclass.csv,cache_line_size=4,cleaning_policy=nop,promotion_policy=always,"
            "lazy_startup=true,target_failover_state=active"),
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_parameter_validation_02(
    mock_check_block, mock_device_empty, mock_path_exists, params
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "1   /dev/sda    WT  {0}".format(params)

    opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "mode",
    [
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ioclass_file=ioclass.csv,cache_line_size=4,cleaning_policy=nop",
        "                ",
        " $$#               ",
        "PT$$#               ",
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_cache_mode_validation_01(
    mock_check_block, mock_device_empty, mock_path_exists, mode
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "1   /dev/sda    {0}".format(mode)

    with pytest.raises(ValueError):
        opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "mode",
    [
        "wt",
        "WT",
        "pt",
        "PT",
        "wb",
        "WB",
        "wa",
        "WA",
        "wA",
        "Wa",
        "wo",
        "WO",
        "wO",
        "Wo",
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_cache_mode_validation_02(
    mock_check_block, mock_device_empty, mock_path_exists, mode
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "1   /dev/sda    {0}".format(mode)

    opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "cache_id",
    [
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "lizard",
        "",
        "#",
        "-1",
        "3.14",
        "3,14",
        "3 14",
        "0",
        "16385",
        "99999999999",
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_cache_id_validation_01(
    mock_check_block, mock_device_empty, mock_path_exists, cache_id
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "{0}   /dev/sda    WT".format(cache_id)

    with pytest.raises(ValueError):
        opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize("cache_id", ["1", "16384", "123"])
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_from_line_cache_id_validation_02(
    mock_check_block, mock_device_empty, mock_path_exists, cache_id
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        ["/dev/sda", "ioclass.csv"]
    )

    line = "{0}   /dev/sda    WT".format(cache_id)

    opencas.cas_config.cache_config.from_line(line)


@pytest.mark.parametrize(
    "params",
    [
        {
            "cache_id": "1",
            "device": "/dev/nvme0n1",
            "cache_mode": "WT",
            "ioclass_file": "ioclass.csv",
            "cleaning_policy": "acp",
            "cache_line_size": "4",
        },
        {
            "cache_id": "16384",
            "device": "/dev/nvme0n1p1",
            "cache_mode": "wb",
            "ioclass_file": "ioclass.csv",
            "cleaning_policy": "nop",
            "cache_line_size": "64",
        },
        {"cache_id": "100", "device": "/dev/sda", "cache_mode": "wb"},
        {
            "cache_id": "2",
            "device": "/dev/dm-1",
            "cache_mode": "wb",
            "cleaning_policy": "nop",
            "cache_line_size": "64",
        },
        {
            "cache_id": "1",
            "device": "/dev/nvme0n1",
            "cache_mode": "WT",
            "cache_line_size": "4",
        },
        {
            "cache_id": "1",
            "device": "/dev/nvme0n1",
            "cache_mode": "wo",
            "cache_line_size": "16",
        },
        {
            "cache_id": "1",
            "device": "/dev/nvme0n1",
            "cache_mode": "wo",
            "promotion_policy": "always",
            "cache_line_size": "16",
            "lazy_startup": "true"
        },
        {
            "cache_id": "1",
            "device": "/dev/nvme0n1",
            "cache_mode": "wo",
            "promotion_policy": "nhit",
            "cache_line_size": "16",
            "target_failover_state": "active",
        },
    ],
)
@mock.patch("os.path.exists")
@mock.patch("opencas.cas_config.cache_config.check_cache_device_empty")
@mock.patch("opencas.cas_config.check_block_device")
def test_cache_config_to_line_from_line(
    mock_check_block, mock_device_empty, mock_path_exists, params
):
    mock_path_exists.side_effect = h.get_mock_os_exists(
        [params["device"], "ioclass.csv"]
    )

    cache_reference = opencas.cas_config.cache_config(**params)

    cache_reference.validate_config(False)

    cache_after = opencas.cas_config.cache_config.from_line(
        cache_reference.to_line()
    )

    assert cache_after.cache_id == cache_reference.cache_id
    assert cache_after.device == cache_reference.device
    assert str.lower(cache_after.cache_mode) == str.lower(
        cache_reference.cache_mode
    )
    assert cache_after.params == cache_reference.params
