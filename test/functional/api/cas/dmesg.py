#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from test_utils.size import Size, Unit


def get_metadata_size(dmesg):
    for s in dmesg.split("\n"):
        if "Metadata capacity:" in s:
            size = re.search("[0-9]* MiB", s).group()
            return Size(int(re.search("[0-9]*", size).group()), Unit.MebiByte)

    raise ValueError("Can't find the metadata size in the privded dmesg output")


def _get_metadata_info(dmesg, section_name):
    for s in dmesg.split("\n"):
        if section_name in s:
            size, unit = re.search("[0-9]* (B|kiB)", s).group().split()
            unit = Unit.KibiByte if unit == "kiB" else Unit.Byte
            return Size(int(re.search("[0-9]*", size).group()), unit)

    raise ValueError(f'"{section_name}" entry doesn\'t exist in the given dmesg output')


def get_md_section_size(section_name, dmesg):
    section_name = section_name.strip()
    section_name += " size"
    return _get_metadata_info(dmesg, section_name)


def get_md_section_offset(section_name, dmesg):
    section_name = section_name.strip()
    section_name += " offset"
    return _get_metadata_info(dmesg, section_name)
