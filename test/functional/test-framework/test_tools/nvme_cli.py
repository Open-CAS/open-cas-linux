#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import json
from core.test_run import TestRun


def format_disk(device, metadata_size=None, block_size=None,
                force=True, format_params=None, reset=True):
    force_param = '-f' if force else ''
    reset_param = '-r' if reset else ''
    format_params = ' '.join(format_params) if format_params else ''
    lbafs = get_lba_formats(device)
    if metadata_size:
        lbafs = [lbaf for lbaf in lbafs if lbaf['metadata_size'] == metadata_size]
        if block_size:
            lbafs = [lbaf for lbaf in lbafs if lbaf['block_size'] == block_size]
        if len(lbafs) == 1:
            TestRun.LOGGER.info(
                f"Formatting device {device.path} with {metadata_size} metadata size "
                f"and {lbafs[0]['block_size']} block size")
            TestRun.executor.run_expect_success(
                f"nvme format {device.path} -l {lbafs[0]['lba_format']} "
                f"{force_param} {reset_param} {format_params}")
            TestRun.LOGGER.info(f"Successfully format device: {device.path}")
        else:
            raise Exception(f"Wrong parameters to format device: {device.path}")
    elif block_size:
        lbafs = [lbaf for lbaf in lbafs if lbaf['block_size'] == block_size]
        if len(lbafs) > 0:
            TestRun.LOGGER.info(
                f"Formatting device {device.path} with {block_size} block size")
            TestRun.executor.run_expect_success(
                f"nvme format {device.path} -b {block_size} "
                f"{force_param} {reset_param} {format_params}")
            TestRun.LOGGER.info(f"Successfully format device: {device.path}")
        else:
            raise Exception(f"Wrong parameters to format device: {device.path}")
    else:
        raise Exception("Cannot format device without specified parameters")


def get_lba_formats(device):
    output = json.loads(TestRun.executor.run_expect_success(
        f"nvme id-ns {device.path} -o json").stdout)
    entries = output['lbafs']
    lbafs = []
    for entry in entries:
        lbaf = {"lba_format": entries.index(entry),
                "metadata_size": entry['ms'],
                "block_size": 2 ** entry['ds'],
                "in_use": entries.index(entry) == output['flbas']}
        lbafs.append(lbaf)
    return lbafs


def get_lba_format_in_use(device):
    lbafs = get_lba_formats(device)
    return next((lbaf for lbaf in lbafs if lbaf['in_use']))
