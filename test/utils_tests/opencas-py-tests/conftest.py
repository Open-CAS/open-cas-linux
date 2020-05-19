#
# Copyright(c) 2012-2020 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import sys


def pytest_configure(config):
    try:
        import helpers
    except ImportError:
        raise Exception("Couldn't import helpers")

    sys.path.append(helpers.find_repo_root() + "/utils")
