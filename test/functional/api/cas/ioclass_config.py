#
# Copyright(c) 2019 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import enum
import re
import string
from datetime import timedelta
from random import randint, randrange

from packaging import version

from core.test_run import TestRun
from test_tools import fs_utils
from test_utils import os_utils
from test_utils.generator import random_string

default_config_file_path = "/tmp/opencas_ioclass.conf"

MAX_IO_CLASS_ID = 32
MAX_IO_CLASS_PRIORITY = 255
MAX_CLASSIFICATION_DELAY = timedelta(seconds=6)
IO_CLASS_CONFIG_HEADER = "IO class id,IO class name,Eviction priority,Allocation"


class IoClass:
    def __init__(self, class_id: int, rule: str = '', priority: int = None,
                 allocation: bool = True):
        self.id = class_id
        self.rule = rule
        self.priority = priority
        self.allocation = allocation

    def __str__(self):
        return (f'{self.id},{self.rule},{"" if self.priority is None else self.priority}'
                f',{int(self.allocation)}')

    def __eq__(self, other):
        return type(other) is IoClass and self.id == other.id and self.rule == other.rule \
               and self.priority == other.priority and self.allocation == other.allocation

    @staticmethod
    def from_string(ioclass_str: str):
        parts = [part.strip() for part in re.split('[,|]', ioclass_str.replace('║', ''))]
        return IoClass(
            class_id=int(parts[0]),
            rule=parts[1],
            priority=int(parts[2]),
            allocation=parts[3] in ['1', 'YES'])

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
    def default():
        return IoClass(0, 'unclassified', 255)

    @staticmethod
    def compare_ioclass_lists(list1: [], list2: []):
        if len(list1) != len(list2):
            return False
        sorted_list1 = sorted(list1, key=lambda c: (c.id, c.priority, c.allocation))
        sorted_list2 = sorted(list2, key=lambda c: (c.id, c.priority, c.allocation))
        for i in range(len(list1)):
            if sorted_list1[i] != sorted_list2[i]:
                return False
        return True

    @staticmethod
    def generate_random_ioclass_list(count: int, max_priority: int = MAX_IO_CLASS_PRIORITY):
        random_list = [IoClass.default().set_priority(randint(0, max_priority))
                       .set_allocation(bool(randint(0, 1)))]
        for i in range(1, count):
            random_list.append(IoClass(i).set_random_rule().set_priority(randint(0, max_priority))
                               .set_allocation(bool(randint(0, 1))))
        return random_list

    def set_priority(self, priority: int):
        self.priority = priority
        return self

    def set_allocation(self, allocation: bool):
        self.allocation = allocation
        return self

    def set_rule(self, rule: str):
        self.rule = rule
        return self

    def set_random_rule(self):
        rules = ["metadata", "direct", "file_size", "directory", "io_class", "extension", "lba",
                 "pid", "process_name", "file_offset", "request_size"]
        if os_utils.get_kernel_version() >= version.Version("4.13"):
            rules.append("wlth")

        rule = rules[randrange(len(rules))]
        self.set_rule(IoClass.add_random_params(rule))
        return self

    @staticmethod
    def add_random_params(rule: str):
        if rule == "directory":
            rule += \
                f":/{random_string(randint(1, 40), string.ascii_letters + string.digits + '/')}"
        elif rule in ["file_size", "lba", "pid", "file_offset", "request_size", "wlth"]:
            rule += f":{Operator(randrange(len(Operator))).name}:{randrange(1000000)}"
        elif rule == "io_class":
            rule += f":{randrange(MAX_IO_CLASS_PRIORITY + 1)}"
        elif rule in ["extension", "process_name"]:
            rule += f":{random_string(randint(1, 10))}"
        if randrange(2):
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
