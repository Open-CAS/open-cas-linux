#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import concurrent


def start_async_func(func, *args):
    """
    Starts asynchronous task and returns an Future object, which in turn returns an
    actual result after triggering result() method on it.
    - result() method is waiting for the task to be completed.
    - done() method returns True when task ended (have a result or ended with an exception)
    otherwise returns False
    """
    executor = concurrent.futures.ThreadPoolExecutor()
    return executor.submit(func, *args)
