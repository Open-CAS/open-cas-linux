#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
from api.cas import ioclass_config, cli_messages
from core.test_run import TestRun
from test_utils.output import CmdException
from test_utils.size import Unit, Size
from tests.io_class.io_class_common import prepare, ioclass_config_path
from api.cas.ioclass_config import IoClass
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fs_utils

headerless_configuration = "1,unclassified,22,1.00"
double_io_class_configuration = "2,file_size:le:4096,1,1.00\n2,file_size:le:4096,1,1.00"
malformed_io_class_allocation = "malformed allocation"
malformed_io_class_eviction_priority = "malformed eviction priority"
malformed_io_class_id = "malformed IO class id"
malformed_io_class_name = "malformed IO class name"

# Illegal configurations and expected error messages:
illegal_io_class_configurations = {
    # Use only 0, 1, 2, 3 and 5 parameters number in one line as integer values
    # 1 parameter
    ",,,1": cli_messages.illegal_io_class_config_L2C1,
    ",,1,": cli_messages.illegal_io_class_config_L2C1,
    ",1,,": cli_messages.illegal_io_class_config_L2C1,
    "1,,,": cli_messages.illegal_io_class_config_L2C2,

    # 2 parameters
    ",,1,1": cli_messages.illegal_io_class_config_L2C1,
    ",1,,1": cli_messages.illegal_io_class_config_L2C1,
    ",1,1,": cli_messages.illegal_io_class_config_L2C1,
    "1,,1,": cli_messages.illegal_io_class_config_L2C2,
    "1,,,1": cli_messages.illegal_io_class_config_L2C2,
    "1,1,,": cli_messages.illegal_io_class_config_L2C4,

    # 3 parameters
    ",1,1,1": cli_messages.illegal_io_class_config_L2C1,
    "1,,1,1": cli_messages.illegal_io_class_config_L2C2,
    "1,1,1,": cli_messages.illegal_io_class_config_L2C4,

    # 5 parameters
    "1,1,1,1,1": cli_messages.illegal_io_class_config_L2,

    # Try to configure IO class ID as: string, negative value or 33
    "IllegalInput,Superblock,22,1": cli_messages.illegal_io_class_invalid_id,
    "-2,Superblock,22,1": cli_messages.illegal_io_class_invalid_id_number,
    "33,Superblock,22,1": cli_messages.illegal_io_class_invalid_id_number,

    # Try to use semicolon, dots or new line as csv delimiters
    "1;1;1;1": cli_messages.illegal_io_class_config_L2,
    "1.1.1.1": cli_messages.illegal_io_class_config_L2,
    "1\n1\n1\n1": cli_messages.illegal_io_class_config_L2,

    # Try to configure eviction priority as: string, negative value or 256
    "1,Superblock,IllegalInput,1": cli_messages.illegal_io_class_invalid_priority,
    "1,Superblock,-2,1": cli_messages.illegal_io_class_invalid_priority_number,
    "1,Superblock,256,1": cli_messages.illegal_io_class_invalid_priority_number,

    # Try to configure allocation as: string, negative value or 2
    "1,Superblock,22,IllegalInput": cli_messages.illegal_io_class_invalid_allocation,
    "1,Superblock,255,-2": cli_messages.illegal_io_class_invalid_allocation_number,
    "1,Superblock,255,2": cli_messages.illegal_io_class_invalid_allocation_number
}


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_io_class_prevent_wrong_configuration():
    """
        title: Open CAS ability to prevent loading wrong configuration.
        description: |
          Check Open CAS ability to prevent loading configuration from wrong configuration file
          like: illegal number of parameters in line, IO class values, using semicolon
          instead of comma, wrong value of eviction, and priority.
        pass_criteria:
          - Wrong configuration must not be loaded
          - There is an appropriate message about wrong io class configuration
    """
    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_size=Size(150, Unit.MiB), core_size=Size(300, Unit.MiB))

    with TestRun.step("Display IO class configuration – shall be default"):
        create_and_load_default_io_class_config(cache)
        loaded_io_classes = cache.list_io_classes()
        loaded_io_classes_str = '\n'.join(str(i) for i in loaded_io_classes)
        TestRun.LOGGER.info(f"Loaded IO class configuration is:\n"
                            f"{IoClass.default_header()}\n{loaded_io_classes_str}")

        config_io_classes = IoClass.csv_to_list(fs_utils.read_file(ioclass_config_path))
        if not IoClass.compare_ioclass_lists(config_io_classes, loaded_io_classes):
            TestRun.fail("Default IO class configuration not loaded correctly.")

    with TestRun.step("Create illegal configuration file containing IO configuration "
                      "without header and check if it can not be loaded."):
        TestRun.LOGGER.info(f"Preparing headerless configuration file with following content:\n"
                            f"{headerless_configuration}")
        fs_utils.write_file(ioclass_config_path, headerless_configuration)
        try_load_malformed_config(cache, config_io_classes,
                                  expected_err_msg=cli_messages.headerless_io_class_config)

    with TestRun.step("Create illegal configuration file containing IO configuration with "
                      "malformed header and check if it can not be loaded."):
        for header, err_message in setup_headers().items():
            config_content = f"{header}\n{IoClass.default()}"
            TestRun.LOGGER.info(f"Testing following header with default IO class:\n"
                                f"{config_content}")
            fs_utils.write_file(ioclass_config_path, config_content)
            try_load_malformed_config(cache, config_io_classes,
                                      expected_err_msg=err_message)

    with TestRun.step("Create illegal configuration file containing double IO class configuration "
                      "and check if it can not be loaded."):
        config_content = f"{IoClass.default_header()}\n{double_io_class_configuration}"
        TestRun.LOGGER.info(f"Testing following configuration file:\n{config_content}")
        fs_utils.write_file(ioclass_config_path, config_content)
        try_load_malformed_config(cache, config_io_classes,
                                  expected_err_msg=cli_messages.double_io_class_config)

    with TestRun.step("Create illegal configuration file containing malformed IO configuration "
                      "with correct header and check if it can not be loaded."):
        for io_config, err_message in illegal_io_class_configurations.items():
            config_content = f"{IoClass.default_header()}\n{io_config}"
            TestRun.LOGGER.info(
                f"Testing following header with default IO class:\n{config_content}")
            fs_utils.write_file(ioclass_config_path, config_content)
            try_load_malformed_config(cache, config_io_classes,
                                      expected_err_msg=err_message)


def try_load_malformed_config(cache, config_io_classes, expected_err_msg):
    try:
        cache.load_io_class(ioclass_config_path)
        TestRun.LOGGER.error("Open CAS accepts malformed configuration.")
        create_and_load_default_io_class_config(cache)
    except CmdException as e:
        TestRun.LOGGER.info(f"Open CAS did not load malformed config file as expected.")
        cli_messages.check_stderr_msg(e.output, expected_err_msg)
        output_io_classes = cache.list_io_classes()
        if not IoClass.compare_ioclass_lists(output_io_classes, config_io_classes):
            output_str = '\n'.join(str(i) for i in output_io_classes)
            TestRun.LOGGER.error(
                f"Loaded IO class config should be default but it is different:\n{output_str}")


def create_and_load_default_io_class_config(cache):
    ioclass_config.create_ioclass_config(ioclass_config_path=ioclass_config_path)
    cache.load_io_class(ioclass_config_path)


def setup_headers():
    default_header = IoClass.default_header_dict()
    correct_id_header = default_header['id']
    correct_name_header = default_header['name']
    correct_eviction_priority_header = default_header['eviction_prio']
    correct_allocation_header = default_header['allocation']

    malformed_io_class_id_header = f"{malformed_io_class_id}," \
                                   f"{correct_name_header}," \
                                   f"{correct_eviction_priority_header}," \
                                   f"{correct_allocation_header}"
    malformed_io_class_name_header = f"{correct_id_header}," \
                                     f"{malformed_io_class_name}," \
                                     f"{correct_eviction_priority_header}," \
                                     f"{correct_allocation_header}"
    malformed_eviction_priority_header = f"{correct_id_header}," \
                                         f"{correct_name_header}," \
                                         f"{malformed_io_class_eviction_priority}," \
                                         f"{correct_allocation_header}"
    malformed_allocation_header = f"{correct_id_header}," \
                                  f"{correct_name_header}," \
                                  f"{correct_eviction_priority_header}," \
                                  f"{malformed_io_class_allocation}"

    return {
        malformed_io_class_id_header: [m.replace("value_template", malformed_io_class_id)
                                       for m in cli_messages.malformed_io_class_header],
        malformed_io_class_name_header: [m.replace("value_template", malformed_io_class_name)
                                         for m in cli_messages.malformed_io_class_header],
        malformed_eviction_priority_header: [m.replace("value_template",
                                                       malformed_io_class_eviction_priority)
                                             for m in cli_messages.malformed_io_class_header],
        malformed_allocation_header: [m.replace("value_template", malformed_io_class_allocation)
                                      for m in cli_messages.malformed_io_class_header]
    }
