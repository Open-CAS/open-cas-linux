#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import unittest.mock as mock
import re
import os
from io import StringIO
from textwrap import dedent


def find_repo_root():
    path = os.getcwd()

    while os.path.realpath(path) != "/":
        if ".git" in os.listdir(path):
            return path

        path = os.path.dirname(path)

    raise Exception(
        "Couldn't find repository root - unable to locate opencas.py"
    )


def get_process_mock(return_value, stdout, stderr):
    process_mock = mock.Mock()
    attrs = {
        "returncode": return_value,
        "stdout": stdout,
        "stderr": stderr
    }
    process_mock.configure_mock(**attrs)

    return process_mock


def get_mock_os_exists(existing_files):
    return lambda x: x in existing_files


def get_hashed_config_list(conf):
    """
    Convert list of config lines to list of config lines hashes,
    drop empty lines
    """
    hashed_conf = [get_conf_line_hash(x) for x in conf]

    return [x for x in hashed_conf if x]


def get_conf_line_hash(line):
    """
    Removes whitespace, lowercases, comments and sorts params if present.
    Returns empty line for comment-only lines

    We don't care about order of params and kinds of whitespace in config lines
    so normalize it to compare. We do care about case in paths, but to simplify
    testing we pretend we don't.
    """

    def sort_params(params):
        return ",".join(sorted(params.split(",")))

    line = line.split("#")[0]

    params_pattern = re.compile(r"(.*?\s)(\S+=\S+)")
    match = params_pattern.search(line)
    if match:
        sorted_params = sort_params(match.group(2))
        line = match.group(1) + sorted_params

    return "".join(line.lower().split())


class MockConfigFile(object):
    def __init__(self, buffer=""):
        self.set_contents(buffer)

    def __enter__(self):
        return self.buffer

    def __exit__(self, *args, **kwargs):
        self.set_contents(self.buffer.getvalue())

    def __call__(self, path, mode):
        if mode == "w":
            self.buffer = StringIO()

        return self

    def read(self):
        return self.buffer.read()

    def write(self, str):
        return self.buffer.write(str)

    def close(self):
        self.set_contents(self.buffer.getvalue())

    def readline(self):
        return self.buffer.readline()

    def __next__(self):
        return self.buffer.__next__()

    def __iter__(self):
        return self

    def set_contents(self, buffer):
        self.buffer = StringIO(dedent(buffer).strip())


class CopyableMock(mock.Mock):
    def __init__(self, *args, **kwargs):
        super(CopyableMock, self).__init__(*args, **kwargs)
        self.copies = []

    def __deepcopy__(self, memo):
        copy = mock.Mock(spec=self)
        self.copies += [copy]
        return copy
