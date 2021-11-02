#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import re
import pytest

from api.cas.cache_config import CacheMode, CacheLineSize, CacheModeTrait
from api.cas.casadm import OutputFormat, print_statistics, start_cache
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.disk_utils import Filesystem
from test_utils.size import Size, Unit

iterations = 64
cache_size = Size(8, Unit.GibiByte)


@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cache_mode", CacheMode.with_any_trait(
    CacheModeTrait.InsertRead | CacheModeTrait.InsertWrite))
@pytest.mark.parametrizex("test_object", ["cache", "core"])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_output_consistency(cache_line_size, cache_mode, test_object):
    """
        title: Test consistency between different cache and core statistics' outputs.
        description: |
          Check if OpenCAS's statistics for cache and core are consistent
          regardless of the output format.
        pass_criteria:
          - Statistics in CSV format matches statistics in table format.
    """
    with TestRun.step("Prepare cache and core."):
        cache_dev = TestRun.disks['cache']
        cache_dev.create_partitions([cache_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks['core']
        core_dev.create_partitions([cache_size * 4])
        core_part = core_dev.partitions[0]
        blocks_in_cache = int(cache_size / cache_line_size.value)

    with TestRun.step("Start cache and add core with a filesystem."):
        cache = start_cache(cache_part, cache_mode, cache_line_size, force=True)
        core_part.create_filesystem(Filesystem.xfs)
        exp_obj = cache.add_core(core_part)

    with TestRun.step("Select object to test."):
        if test_object == "cache":
            tested_object = cache
            flush = tested_object.flush_cache
        elif test_object == "core":
            tested_object = exp_obj
            flush = tested_object.flush_core
        else:
            TestRun.LOGGER.error("Wrong type of device to read statistics from.")

    for _ in TestRun.iteration(range(iterations), f"Run configuration {iterations} times"):
        with TestRun.step(f"Reset stats and run workload on the {test_object}."):
            tested_object.reset_counters()
            # Run workload on a random portion of the tested object's capacity,
            # not too small, but not more than half the size
            random_count = random.randint(blocks_in_cache / 32, blocks_in_cache / 2)
            TestRun.LOGGER.info(f"Run workload on {(random_count / blocks_in_cache * 100):.2f}% "
                                f"of {test_object}'s capacity.")
            dd_builder(cache_mode, cache_line_size, random_count, exp_obj).run()

        with TestRun.step(f"Flush {test_object} and get statistics from different outputs."):
            flush()
            csv_stats = get_stats_from_csv(
                cache.cache_id, tested_object.core_id if test_object == "core" else None
            )
            table_stats = get_stats_from_table(
                cache.cache_id, tested_object.core_id if test_object == "core" else None
            )

        with TestRun.step("Compare statistics between outputs."):
            if csv_stats != table_stats:
                TestRun.LOGGER.error(f"Inconsistent outputs:\n{csv_stats}\n\n{table_stats}")


def get_stats_from_csv(cache_id: int, core_id: int = None):
    """
    'casadm -P' csv output has two lines:
    1st - statistics names with units
    2nd - statistics values
    This function returns dictionary with statistics names with units as keys
    and statistics values as values.
    """
    output = print_statistics(cache_id, core_id, output_format=OutputFormat.csv)

    output = output.stdout.splitlines()

    keys = output[0].split(",")
    values = output[1].split(",")

    # return the keys and the values as a dictionary
    return dict(zip(keys, values))


def get_stats_from_table(cache_id: int, core_id: int = None):
    """
    'casadm -P' table output has a few sections:
    1st - config section with two columns
    remaining - table sections with four columns
    This function returns dictionary with statistics names with units as keys
    and statistics values as values.
    """
    output = print_statistics(cache_id, core_id, output_format=OutputFormat.table)
    output = output.stdout.splitlines()

    output_parts = []

    # split 'casadm -P' output to sections and remove blank lines
    j = 0
    for i, line in enumerate(output):
        if line == "" or i == len(output) - 1:
            output_parts.append(output[j:i])
            j = i + 1

    # the first part is config section
    conf_section = output_parts.pop(0)
    keys, values = (parse_core_conf_section(conf_section) if core_id
                    else parse_cache_conf_section(conf_section))

    # parse each remaining section
    for section in output_parts:
        # the remaining parts are table sections
        part_of_keys, part_of_values = parse_tables_section(section)

        # receive keys and values lists from every section
        keys.extend(part_of_keys)
        values.extend(part_of_values)

    # return the keys and the values as a dictionary
    return dict(zip(keys, values))


def parse_conf_section(table_as_list: list, column_width: int):
    """
    The 'column_width' parameter is the width of the first column
    of the first section in the statistics output in table format.
    The first section in the 'casadm -P' output have two columns.
    """
    keys = []
    values = []
    # reformat table
    table_as_list = separate_values_to_two_lines(table_as_list, column_width)

    # split table lines to statistic name and its value
    # and save them to keys and values tables
    for line in table_as_list:
        splitted_line = []

        # move unit from value to statistic name if needed
        sqr_brackets_counter = line.count("[")
        if sqr_brackets_counter:
            addition = line[line.index("["):line.index("]") + 1]
            splitted_line.insert(0, line[:column_width] + addition)
            splitted_line.insert(1, line[column_width:].replace(addition, ""))
        else:
            splitted_line.insert(0, line[:column_width])
            splitted_line.insert(1, line[column_width:])

        # remove whitespaces
        # save each statistic name (with unit) to keys
        keys.append(re.sub(r'\s+', ' ', splitted_line[0]).strip())
        # save each statistic value to values
        values.append(re.sub(r'\s+', ' ', splitted_line[1]).strip())

    return keys, values


def parse_cache_conf_section(table_as_list: list):
    id_row = _find_id_row(table_as_list)
    column_width = _check_first_column_width(id_row)
    return parse_conf_section(table_as_list, column_width)


def parse_core_conf_section(table_as_list: list):
    id_row = _find_id_row(table_as_list)
    column_width = _check_first_column_width(id_row)
    return parse_conf_section(table_as_list, column_width)


def _find_id_row(table_as_list: list):
    """
    Finds Id row in the first section of the 'casadm -P' output.
    """
    for line in table_as_list:
        if "Id" in line:
            return line
    raise Exception("Cannot find Id row in the 'casadm -P' output")


def _check_first_column_width(id_row: str):
    """
    Return index of the Id number in the Id row in the first section of the 'casadm -P' output.
    """
    return re.search(r"\d+", id_row).regs[0][0]


def separate_values_to_two_lines(table_as_list: list, column_width: int):
    """
    If there are two values of the one statistic in different units in one line,
    replace this line with two lines, each containing value in one unit.
    """
    for i, line in enumerate(table_as_list):
        has_two_units = line.count(" / ")
        if has_two_units:
            table_as_list.remove(line)
            value_parts = line[column_width:].split(" / ")

            table_as_list.insert(i, line[:column_width] + value_parts[0])
            table_as_list.insert(i + 1, line[:column_width] + value_parts[1])

    return table_as_list


def parse_tables_section(table_as_list: list):
    """
    The remaining sections in the 'casadm -P' output have four columns.
    1st: Usage statistics - statistics names
    2nd: Count - values dependent on units
    3rd: % - percentage values
    4th: Units - full units for values stored in 2nd column
    """
    keys = []
    values = []

    # remove table header - 3 lines, it is useless
    table_as_list = table_as_list[3:]

    # remove separator lines, it is also useless
    for line in table_as_list:
        if is_table_separator(line):
            table_as_list.remove(line)

    # split lines to columns and remove whitespaces
    for line in table_as_list:
        splitted_line = re.split(r'│|\|', line)
        for i in range(len(splitted_line)):
            splitted_line[i] = splitted_line[i].strip()

        # save keys and values in order:
        # key: statistic name and unit
        # value: value in full unit
        keys.append(f'{splitted_line[1]} [{splitted_line[4]}]')
        values.append(splitted_line[2])
        # key: statistic name and percent sign
        # value: value as percentage
        keys.append(f'{splitted_line[1]} [%]')
        values.append(splitted_line[3])

    return keys, values


def is_table_separator(line: str):
    """
    Tables in the 'casadm -P' output have plus signs only on separator lines.
    """
    return ('+' or '╪' or '╧') in line


def dd_builder(cache_mode, cache_line_size, count, device):
    dd = (Dd()
          .block_size(cache_line_size.value)
          .count(count))

    if CacheModeTrait.InsertRead in CacheMode.get_traits(cache_mode):
        dd.input(device.path).output("/dev/null").iflag("direct")
    else:
        dd.input("/dev/urandom").output(device.path).oflag("direct")

    return dd
