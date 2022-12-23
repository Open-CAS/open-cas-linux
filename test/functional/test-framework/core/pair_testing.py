#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

# The MIT License (MIT)
#
# Copyright (c) 2004-2020 Holger Krekel and others
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from itertools import product, combinations
import random

from core.test_run import TestRun

def testcase_id(param_set):
    if len(param_set.values) == 1:
        return param_set.values[0]

    return "-".join([str(value) for value in param_set.values])


def generate_pair_testing_testcases(*argvals):
    """
    Generate test_cases from provided argument values lists in such way that each possible
    (argX, argY) pair will be used.
    """
    # if only one argument is used, yield from it
    if len(argvals) == 1:
        for val in argvals[0]:
            yield (val,)

    # append argument index to argument values list to avoid confusion when there are two arguments
    # with the same type
    for i, arg in enumerate(argvals):
        for j, val in enumerate(arg):
            arg[j] = (i, val)

    # generate all possible test cases
    all_test_cases = list(product(*argvals))
    random.seed(TestRun.random_seed)
    random.shuffle(all_test_cases)

    used_pairs = set()
    for tc in all_test_cases:
        current_pairs = set(combinations(tc, 2))
        # if cardinality of (current_pairs & used_pairs) is lesser than cardinality of current_pairs
        # it means not all argument pairs in this tc have been used. return current tc
        # and update used_pairs set
        if len(current_pairs & used_pairs) != len(current_pairs):
            used_pairs.update(current_pairs)
            # unpack testcase by deleting argument index
            yield list(list(zip(*tc))[1])


def register_testcases(metafunc, argnames, argvals):
    """
    Add custom parametrization test cases. Based on metafunc's parametrize method.
    """
    from _pytest.python import CallSpec2, _find_parametrized_scope
    from _pytest.mark import ParameterSet
    from _pytest.fixtures import scope2index

    parameter_sets = [ParameterSet(values=val, marks=[], id=None) for val in argvals]
    metafunc._validate_if_using_arg_names(argnames, False)

    arg_value_types = metafunc._resolve_arg_value_types(argnames, False)

    ids = [testcase_id(param_set) for param_set in parameter_sets]

    scope = _find_parametrized_scope(argnames, metafunc._arg2fixturedefs, False)
    scopenum = scope2index(scope, descr=f"parametrizex() call in {metafunc.function.__name__}")

    calls = []
    for callspec in metafunc._calls or [CallSpec2(metafunc)]:
        for param_index, (param_id, param_set) in enumerate(zip(ids, parameter_sets)):
            newcallspec = callspec.copy()
            newcallspec.setmulti2(
                arg_value_types,
                argnames,
                param_set.values,
                param_id,
                param_set.marks,
                scopenum,
                param_index,
            )
            calls.append(newcallspec)

    metafunc._calls = calls
