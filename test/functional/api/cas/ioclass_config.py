#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

from datetime import timedelta

from core.test_run import TestRun

default_config_file_path = "/tmp/opencas_ioclass.conf"

MAX_IO_CLASS_ID = 32

MAX_CLASSIFICATION_DELAY = timedelta(seconds=6)


def create_ioclass_config(
    add_default_rule: bool = True, ioclass_config_path: str = default_config_file_path
):
    TestRun.LOGGER.info(f"Creating config file {ioclass_config_path}")
    output = TestRun.executor.run(
        'echo "IO class id,IO class name,Eviction priority,Allocation" '
        + f"> {ioclass_config_path}"
    )
    if output.exit_code != 0:
        raise Exception(
            "Failed to create ioclass config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )
    if add_default_rule:
        output = TestRun.executor.run(
            f'echo "0,unclassified,22,1" >> {ioclass_config_path}'
        )
        if output.exit_code != 0:
            raise Exception(
                "Failed to create ioclass config file. "
                + f"stdout: {output.stdout} \n stderr :{output.stderr}"
            )


def remove_ioclass_config(ioclass_config_path: str = default_config_file_path):
    TestRun.LOGGER.info(f"Removing config file {ioclass_config_path}")
    output = TestRun.executor.run(f"rm -f {ioclass_config_path}")
    if output.exit_code != 0:
        raise Exception(
            "Failed to remove config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )


def add_ioclass(
    ioclass_id: int,
    rule: str,
    eviction_priority: int,
    allocation: bool,
    ioclass_config_path: str = default_config_file_path,
):
    new_ioclass = f"{ioclass_id},{rule},{eviction_priority},{int(allocation)}"
    TestRun.LOGGER.info(
        f"Adding rule {new_ioclass} " + f"to config file {ioclass_config_path}"
    )

    output = TestRun.executor.run(
        f'echo "{new_ioclass}" >> {ioclass_config_path}'
    )
    if output.exit_code != 0:
        raise Exception(
            "Failed to append ioclass to config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )


def get_ioclass(ioclass_id: int, ioclass_config_path: str = default_config_file_path):
    TestRun.LOGGER.info(
        f"Retrieving rule no.{ioclass_id} " + f"from config file {ioclass_config_path}"
    )
    output = TestRun.executor.run(f"cat {ioclass_config_path}")
    if output.exit_code != 0:
        raise Exception(
            "Failed to read ioclass config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )

    ioclass_config = output.stdout.splitlines()

    for ioclass in ioclass_config:
        if int(ioclass.split(",")[0]) == ioclass_id:
            return ioclass


def remove_ioclass(
    ioclass_id: int, ioclass_config_path: str = default_config_file_path
):
    TestRun.LOGGER.info(
        f"Removing rule no.{ioclass_id} " + f"from config file {ioclass_config_path}"
    )
    output = TestRun.executor.run(f"cat {ioclass_config_path}")
    if output.exit_code != 0:
        raise Exception(
            "Failed to read ioclass config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )

    old_ioclass_config = output.stdout.splitlines()
    config_header = old_ioclass_config[0]

    # First line in valid config file is always a header, not a rule - it is
    # already extracted above
    new_ioclass_config = [
        x for x in old_ioclass_config[1:] if int(x.split(",")[0]) != ioclass_id
    ]

    new_ioclass_config.insert(0, config_header)

    if len(new_ioclass_config) == len(old_ioclass_config):
        raise Exception(
            f"Failed to remove ioclass {ioclass_id} from config file {ioclass_config_path}"
        )

    new_ioclass_config_str = "\n".join(new_ioclass_config)
    output = TestRun.executor.run(
        f'echo "{new_ioclass_config_str}" > {ioclass_config_path}'
    )
    if output.exit_code != 0:
        raise Exception(
            "Failed to save new ioclass config. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )
