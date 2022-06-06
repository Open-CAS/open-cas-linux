#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import enum
import functools
import random
import re
import string
from datetime import timedelta

from packaging import version

from core.test_run import TestRun
from test_tools import fs_utils
from test_utils import os_utils
from test_utils.generator import random_string

default_config_file_path = "/tmp/opencas_ioclass.conf"

MAX_IO_CLASS_ID = 32
MAX_IO_CLASS_PRIORITY = 255
DEFAULT_IO_CLASS_ID = 0
DEFAULT_IO_CLASS_PRIORITY = 255
DEFAULT_IO_CLASS_RULE = "unclassified"
MAX_CLASSIFICATION_DELAY = timedelta(seconds=6)
IO_CLASS_CONFIG_HEADER = "IO class id,IO class name,Eviction priority,Allocation"


@functools.total_ordering
class IoClass:
    def __init__(self, class_id: int, rule: str = '', priority: int = None,
                 allocation: str = "1.00"):
        self.id = class_id
        self.rule = rule
        self.priority = priority
        self.allocation = allocation

    def __str__(self):
        return (f'{self.id},{self.rule},{"" if self.priority is None else self.priority}'
                f',{self.allocation}')

    def __eq__(self, other):
        return ((self.id, self.rule, self.priority, self.allocation)
                == (other.id, other.rule, other.priority, other.allocation))

    def __lt__(self, other):
        return ((self.id, self.rule, self.priority, self.allocation)
                < (other.id, other.rule, other.priority, other.allocation))

    @staticmethod
    def from_string(ioclass_str: str):
        parts = [part.strip() for part in re.split('[,|]', ioclass_str.replace('║', ''))]
        return IoClass(
            class_id=int(parts[0]),
            rule=parts[1],
            priority=int(parts[2]),
            allocation=parts[3])

    @staticmethod
    def list_to_csv(ioclass_list: [], add_default_rule: bool = True):
        list_copy = ioclass_list[:]
        if add_default_rule and not len([c for c in list_copy if c.id == 0]):
            list_copy.insert(0, IoClass.default())
        list_copy.insert(0, IO_CLASS_CONFIG_HEADER)
        return '\n'.join(str(c) for c in list_copy)

    @staticmethod
    def csv_to_list(csv: str):
        ioclass_list = []
        for line in csv.splitlines():
            if line.strip() == IO_CLASS_CONFIG_HEADER:
                continue
            ioclass_list.append(IoClass.from_string(line))
        return ioclass_list

    @staticmethod
    def save_list_to_config_file(ioclass_list: [],
                                 add_default_rule: bool = True,
                                 ioclass_config_path: str = default_config_file_path):
        TestRun.LOGGER.info(f"Creating config file {ioclass_config_path}")
        fs_utils.write_file(ioclass_config_path,
                            IoClass.list_to_csv(ioclass_list, add_default_rule))

    @staticmethod
    def default(priority=DEFAULT_IO_CLASS_PRIORITY, allocation="1.00"):
        return IoClass(DEFAULT_IO_CLASS_ID, DEFAULT_IO_CLASS_RULE, priority, allocation)

    @staticmethod
    def default_header_dict():
        return {
            "id": "IO class id",
            "name": "IO class name",
            "eviction_prio": "Eviction priority",
            "allocation": "Allocation"
        }

    @staticmethod
    def default_header():
        return ','.join(IoClass.default_header_dict().values())

    @staticmethod
    def compare_ioclass_lists(list1: [], list2: []):
        return sorted(list1) == sorted(list2)

    @staticmethod
    def generate_random_ioclass_list(count: int, max_priority: int = MAX_IO_CLASS_PRIORITY):
        random_list = [IoClass.default(priority=random.randint(0, max_priority),
                                       allocation=f"{random.randint(0, 100) / 100:0.2f}")]
        for i in range(1, count):
            random_list.append(IoClass(i, priority=random.randint(0, max_priority),
                                       allocation=f"{random.randint(0, 100) / 100:0.2f}")
                               .set_random_rule())
        return random_list

    def set_random_rule(self):
        rules = ["metadata", "direct", "file_size", "directory", "io_class",
                 "extension", "file_name_prefix", "lba", "pid", "process_name",
                 "file_offset", "request_size"]
        if os_utils.get_kernel_version() >= version.Version("4.13"):
            rules.append("wlth")

        rule = random.choice(rules)
        self.rule = IoClass.add_random_params(rule)
        return self

    @staticmethod
    def add_random_params(rule: str):
        if rule == "directory":
            allowed_chars = string.ascii_letters + string.digits + '/'
            rule += f":/{random_string(random.randint(1, 40), allowed_chars)}"
        elif rule in ["file_size", "lba", "pid", "file_offset", "request_size", "wlth"]:
            rule += f":{Operator(random.randrange(len(Operator))).name}:{random.randrange(1000000)}"
        elif rule == "io_class":
            rule += f":{random.randrange(MAX_IO_CLASS_PRIORITY + 1)}"
        elif rule in ["extension", "process_name", "file_name_prefix"]:
            rule += f":{random_string(random.randint(1, 10))}"
        if random.randrange(2):
            rule += "&done"
        return rule


class Operator(enum.Enum):
    eq = 0
    gt = 1
    ge = 2
    lt = 3
    le = 4


# TODO: replace below methods with methods using IoClass
def create_ioclass_config(
        add_default_rule: bool = True, ioclass_config_path: str = default_config_file_path
):
    TestRun.LOGGER.info(f"Creating config file {ioclass_config_path}")
    output = TestRun.executor.run(
        f'echo {IO_CLASS_CONFIG_HEADER} > {ioclass_config_path}'
    )
    if output.exit_code != 0:
        raise Exception(
            "Failed to create ioclass config file. "
            + f"stdout: {output.stdout} \n stderr :{output.stderr}"
        )

    if add_default_rule:
        output = TestRun.executor.run(
            f'echo "{DEFAULT_IO_CLASS_ID},{DEFAULT_IO_CLASS_RULE},{DEFAULT_IO_CLASS_PRIORITY},"'
            + f'"1.00" >> {ioclass_config_path}'
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
        allocation,
        ioclass_config_path: str = default_config_file_path,
):
    new_ioclass = f"{ioclass_id},{rule},{eviction_priority},{allocation}"
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
        f"Retrieving rule no. {ioclass_id} " + f"from config file {ioclass_config_path}"
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
