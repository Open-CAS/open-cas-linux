#
# Copyright(c) 2020-2021 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import random
import re
from collections import OrderedDict

import pytest

from api.cas.cache_config import CacheMode, CacheLineSize, CacheModeTrait
from api.cas.casadm import OutputFormat, print_statistics, start_cache
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_utils.size import Size, Unit

iterations = 4
cache_size = Size(4, Unit.GibiByte)


@pytest.mark.parametrizex("cache_mode", CacheMode.with_any_trait(
    CacheModeTrait.InsertRead | CacheModeTrait.InsertWrite
))
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_output_consistency(cache_mode):
    """
        title: Test consistency between different cache and core statistics' output formats.
        description: |
          Check if OpenCAS's statistics for cache and core are consistent
          regardless of the output format.
        pass_criteria:
          - Statistics in CSV format match statistics in table format.
    """
    cache_line_size = random.choice(list(CacheLineSize))

    with TestRun.step("Prepare cache and core devices"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([cache_size])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([cache_size * 4])
        core_part = core_dev.partitions[0]
        blocks_in_cache = int(cache_size / cache_line_size.value)

    with TestRun.step("Start cache and add core"):
        cache = start_cache(cache_part, cache_mode, cache_line_size, force=True)
        exp_obj = cache.add_core(core_part)

    for _ in TestRun.iteration(range(iterations), f"Run configuration {iterations} times"):
        with TestRun.step("Reset stats and run workload"):
            cache.reset_counters()
            # Run workload on a random portion of the tested object's capacity,
            # not too small, but not more than half the size
            random_count = random.randint(blocks_in_cache // 32, blocks_in_cache // 2)
            TestRun.LOGGER.info(f"Run workload on {(random_count / blocks_in_cache * 100):.2f}% "
                                "of cache's capacity.")
            dd_builder(cache_mode, cache_line_size, random_count, exp_obj).run()

        with TestRun.step("Get statistics from different outputs"):
            cache_csv_output = print_statistics(cache.cache_id, output_format=OutputFormat.csv)
            cache_table_output = print_statistics(cache.cache_id, output_format=OutputFormat.table)
            cache_csv_stats = get_stats_from_csv(cache_csv_output)
            cache_table_stats = get_stats_from_table(cache_table_output)

            core_csv_output = print_statistics(
                exp_obj.cache_id, exp_obj.core_id, output_format=OutputFormat.csv
            )
            core_table_output = print_statistics(
                exp_obj.cache_id, exp_obj.core_id, output_format=OutputFormat.table
            )
            core_csv_stats = get_stats_from_csv(core_csv_output)
            core_table_stats = get_stats_from_table(core_table_output)

        with TestRun.step("Compare statistics between outputs"):
            TestRun.LOGGER.info("Cache stats comparison")
            compare_csv_and_table(cache_csv_stats, cache_table_stats)
            TestRun.LOGGER.info("Core stats comparison")
            compare_csv_and_table(core_csv_stats, core_table_stats)


def get_stats_from_csv(output):
    """
    'casadm -P' csv output has two lines:
    1st - statistics names with units
    2nd - statistics values
    This function returns dictionary with statistics names with units as keys
    and statistics values as values.
    """
    output = output.stdout.splitlines()

    keys = output[0].split(",")
    values = output[1].split(",")

    # return the keys and the values as a dictionary
    return OrderedDict(zip(keys, values))


def get_stats_from_table(output):
    """
    'casadm -P' table output has a few sections:
    1st - config section with two columns
    remaining - table sections with four columns
    This function returns dictionary with statistics names with units as keys
    and statistics values as values.
    """
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
    id_row = _find_id_row(conf_section)
    column_width = _check_first_column_width(id_row)
    stat_dict = parse_conf_section(conf_section, column_width)

    # parse each remaining section
    for section in output_parts:
        # the remaining parts are table sections
        part_of_stat_dict = parse_tables_section(section)

        # receive keys and values from every section
        stat_dict.update(part_of_stat_dict)

    # return the keys and the values as a dictionary
    return stat_dict


def parse_conf_section(table_as_list: list, column_width: int):
    """
    The 'column_width' parameter is the width of the first column
    of the first section in the statistics output in table format.
    The first section in the 'casadm -P' output have two columns.
    """
    stat_dict = OrderedDict()

    # reformat table
    table_as_list = separate_values_to_two_lines(table_as_list, column_width)

    # 'Dirty for' in csv has one entry with and one without unit, we want to match that
    # and set this to False after the first entry is processed
    process_dirty_for = True

    # split table lines to statistic name and its value
    # and save them to keys and values tables
    for line in table_as_list:
        key, value = line[:column_width], line[column_width:]
        is_dirty_for = key.startswith("Dirty for")
        # move unit from value to statistic name if needed
        if "[" in value and (not is_dirty_for or process_dirty_for):
            unit = line[line.index("["):line.index("]") + 1]
            key = key + unit
            value = value.replace(unit, "")
            if is_dirty_for:
                process_dirty_for = False

        # remove whitespaces
        key = re.sub(r"\s+", " ", key).strip()
        value = re.sub(r"\s+", " ", value).strip()
        stat_dict[key] = value

    return stat_dict


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
        has_two_units = " / " in line
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
    stats_dict = OrderedDict()

    # remove table header - 3 lines, it is useless
    table_as_list = table_as_list[3:]

    # remove separator lines, it is also useless
    for line in table_as_list:
        if is_table_separator(line):
            table_as_list.remove(line)

    # split lines to columns and remove whitespaces
    for line in table_as_list:
        split_line = re.split(r"[│|]", line)
        split_line = [part.strip() for part in split_line]

        # save keys and values in order:
        # key: statistic name and unit
        # value: value in full unit
        key = f"{split_line[1]} [{split_line[4]}]"
        value = split_line[2]
        stats_dict[key] = value
        # key: statistic name and percent sign
        # value: value as percentage
        key = f"{split_line[1]} [%]"
        value = split_line[3]
        stats_dict[key] = value

    return stats_dict


def is_table_separator(line: str):
    """
    Tables in the 'casadm -P' output have plus signs only on separator lines.
    """
    return ('+' or '╪' or '╧') in line


def compare_csv_and_table(csv_stats, table_stats):
    if csv_stats != table_stats:
        wrong_keys = []
        dirty_for_similar = True
        for key in csv_stats:
            if csv_stats[key] != table_stats[key]:
                if not key.startswith("Dirty for") or not dirty_for_similar:
                    wrong_keys.append(key)
                    continue
                if "[s]" not in key:
                    continue
                # 'Dirty for' values might differ by 1 [s]
                dirty_for_similar = int(csv_stats[key]) - int(table_stats[key]) in {-1, 1}
                if not dirty_for_similar:
                    wrong_keys.append(key)

        if len(csv_stats) != len(table_stats) or wrong_keys:
            TestRun.LOGGER.error(
                f"Inconsistent outputs:\n{csv_stats}\n\n{table_stats}"
                + (f"\nWrong keys: {', '.join(wrong_keys)}" if wrong_keys else "")
            )


def dd_builder(cache_mode, cache_line_size, count, device):
    dd = (Dd()
          .block_size(cache_line_size.value)
          .count(count))

    if CacheModeTrait.InsertRead in CacheMode.get_traits(cache_mode):
        dd.input(device.path).output("/dev/null").iflag("direct")
    else:
        dd.input("/dev/urandom").output(device.path).oflag("direct")

    return dd
