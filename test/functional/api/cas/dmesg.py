#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from test_utils.dmesg import get_dmesg
from types.size import Size, Unit


def get_metadata_size_on_device(cache_id: int) -> Size:
    dmesg_reversed = list(reversed(get_dmesg().split("\n")))
    cache_name = "cache" + str(cache_id)
    cache_dmesg = "\n".join(line for line in dmesg_reversed if re.search(f"{cache_name}:", line))
    try:
        return _get_metadata_info(dmesg=cache_dmesg, section_name="Metadata size on device")
    except ValueError:
        raise ValueError("Can't find the metadata size in dmesg output")


def _get_metadata_info(dmesg, section_name) -> Size:
    for s in dmesg.split("\n"):
        if section_name in s:
            size, unit = re.search("\\d+ (B|kiB)", s).group().split()
            unit = Unit.KibiByte if unit == "kiB" else Unit.Byte
            return Size(int(re.search("\\d+", size).group()), unit)

    raise ValueError(f'"{section_name}" entry doesn\'t exist in the given dmesg output')


def get_md_section_size(section_name, dmesg) -> Size:
    section_name = section_name.strip()
    section_name += " size"
    return _get_metadata_info(dmesg, section_name)


def get_md_section_offset(section_name, dmesg) -> Size:
    section_name = section_name.strip()
    section_name += " offset"
    return _get_metadata_info(dmesg, section_name)
