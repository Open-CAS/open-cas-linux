#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import subprocess
import unittest.mock as mock

from opencas import casadm
from helpers import get_process_mock


@mock.patch("subprocess.run")
def test_run_cmd_01(mock_run):
    mock_run.return_value = get_process_mock(0, "successes", "errors")
    result = casadm.run_cmd(["casadm", "-L"])

    assert result.exit_code == 0
    assert result.stdout == "successes"
    assert result.stderr == "errors"
    mock_run.assert_called_once_with(
        ["casadm", "-L"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=mock.ANY,
    )


@mock.patch("subprocess.run")
def test_run_cmd_02(mock_run):
    mock_run.return_value = get_process_mock(4, "successes", "errors")
    with pytest.raises(casadm.CasadmError):
        casadm.run_cmd(["casadm", "-L"])


@mock.patch("subprocess.run")
def test_get_version_01(mock_run):
    mock_run.return_value = get_process_mock(0, "0.0.1", "errors")
    result = casadm.get_version()

    assert result.exit_code == 0
    assert result.stdout == "0.0.1"
    assert result.stderr == "errors"
    mock_run.assert_called_once_with(
        [casadm.casadm_path, "--version", "--output-format", "csv"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=mock.ANY,
    )


@mock.patch("subprocess.run")
def test_get_version_02(mock_run):
    mock_run.return_value = get_process_mock(4, "successes", "errors")
    with pytest.raises(casadm.CasadmError):
        casadm.get_version()
