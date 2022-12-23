#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import os
import wget
import base64
import posixpath
import random
import tempfile
import lxml.etree as etree
from collections import namedtuple

from core.test_run import TestRun
from test_tools import fs_utils
from test_tools.fs_utils import create_directory, check_if_file_exists, write_file


class PeachFuzzer:
    """
    API to work with Peach Fuzzer tool in Test-Framework.
    Peach Fuzzer is used only for generating fuzzed values that later are used in Test-Framework
    in order to execute fuzzed CLI commands or to prepare fuzzed config files.
    """

    peach_fuzzer_3_0_url = "https://sourceforge.net/projects/peachfuzz/files/Peach/3.0/" \
                           "peach-3.0.202-linux-x86_64-release.zip"
    base_dir = "/root/Fuzzy"
    peach_dir = "peach-3.0.202-linux-x86_64-release"
    xml_config_template = posixpath.join(posixpath.dirname(__file__), "config_template.xml")
    xml_config_file = posixpath.join(base_dir, "fuzzerConfig.xml")
    xml_namespace = "http://peachfuzzer.com/2012/Peach"
    fuzzy_output_file = posixpath.join(base_dir, "fuzzedParams.txt")
    tested_param_placeholder = b"{param}"
    # escape backslash first, so it doesn't interfere with escaping other characters
    escape_chars = '\\\n"\'&|;()`<>$! '

    @classmethod
    def get_fuzzed_command(cls, command_template: bytes, count: int):
        """
        Generate command with fuzzed parameter provided on command_template.
        Command is ready to be executed with test executor
        :param command_template: byte string with command to be executed.
               parameter to be replaced with fuzzed string has to be tested_param_placeholder
        :param count: amount of fuzzed commands to generate
        :returns: named tuple with fuzzed param and CLI ready to be executed with Test-Framework
        executors. Param is returned in order to implement correct values checkers in the tests
        """
        TestRun.LOGGER.info(f"Try to get commands with fuzzed parameters")
        FuzzedCommand = namedtuple('FuzzedCommand', ['param', 'command'])
        if cls.tested_param_placeholder not in command_template:
            TestRun.block("No param placeholder is found in command template!")
        cmd_prefix = b"echo "
        cmd_suffix = b" | base64 --decode | sh"
        for fuzzed_parameter in cls.generate_peach_fuzzer_parameters(count):
            yield FuzzedCommand(fuzzed_parameter,
                                cmd_prefix + base64.b64encode(command_template.replace(
                                    cls.tested_param_placeholder, fuzzed_parameter)) + cmd_suffix)

    @classmethod
    def generate_peach_fuzzer_parameters(cls, count: int):
        """
        Generate fuzzed parameter according to Peach Fuzzer XML config
        Fuzzed parameter later can be used for either generating cli command or config.
        :param count: amount of fuzzed strings to generate
        :returns: fuzzed value in byte string
        """
        if not cls._is_installed():
            TestRun.LOGGER.info("Try to install Peach Fuzzer")
            cls._install()
        if not cls._is_xml_config_prepared():
            TestRun.block("No Peach Fuzzer XML config needed to generate fuzzed values was found!")
        fs_utils.remove(cls.fuzzy_output_file, force=True, ignore_errors=True)
        TestRun.LOGGER.info(f"Generate {count} unique fuzzed values")
        cmd = f"cd {cls.base_dir}; {cls.peach_dir}/peach --range 0,{count - 1} " \
              f"--seed {random.randrange(2 ** 32)} {cls.xml_config_file} > " \
              f"{cls.base_dir}/peachOutput.log"
        TestRun.executor.run_expect_success(cmd)
        if not check_if_file_exists(cls.fuzzy_output_file):
            TestRun.block("No expected fuzzy output file was found!")

        # process fuzzy output file locally on the controller as it can be very big
        local_fuzzy_file = tempfile.NamedTemporaryFile(delete=False)
        local_fuzzy_file.close()
        TestRun.executor.rsync_from(cls.fuzzy_output_file, local_fuzzy_file.name)
        with open(local_fuzzy_file.name, "r") as fd:
            for fuzzed_param_line in fd:
                fuzzed_param_bytes = base64.b64decode(fuzzed_param_line)
                fuzzed_param_bytes = cls._escape_special_chars(fuzzed_param_bytes)
                yield fuzzed_param_bytes

    @classmethod
    def generate_config(cls, data_model_config: list):
        """
        Generate Peach Fuzzer XML config based on template provided in xml_config_template
        and data template passed as an argument.
        :param data_model_config: dictionary with config that has to be used for generating
        DataModel section in PeachFuzzer XML config. Config can be stored in test in more compact
        form, e.g. in yaml, and can be converted to dict just before passing to this function.
        Example of such config in yaml:
            - name: String
              attributes:
                name: CacheId
                value: '1'
                size: '14'
                mutable: 'true'
              children:
               - name: Hint
                 attributes:
                   name: NumericalString
                   value: 'true'
        """

        if not posixpath.exists(cls.xml_config_template):
            TestRun.block("Peach fuzzer xml config template not found!")
        root = etree.parse(cls.xml_config_template)
        data_model = root.find(f'{{{cls.xml_namespace}}}DataModel[@name="Value"]')
        cls.__create_xml_nodes(data_model, data_model_config)
        create_directory(cls.base_dir, True)
        write_file(cls.xml_config_file, etree.tostring(root, encoding="unicode"))

    @classmethod
    def copy_config(cls, config_file: str):
        """
        Instead of generating config with "generate_config" method, config can be prepared manually
        and just passed as is to PeachFuzzer.
        :param config_file: Peach Fuzzer XML config to be copied to the DUT
        """
        if not posixpath.exists(config_file):
            TestRun.block("Peach fuzzer xml config to be copied doesn't exist!")
        create_directory(cls.base_dir, True)
        TestRun.executor.rsync_to(config_file, cls.xml_config_file)

    @classmethod
    def __create_xml_nodes(cls, xml_node, config):
        """
        Create XML code for Peach Fuzzer based on python dict config
        """
        for element in config:
            new_node = etree.Element(element["name"])
            for attr_name, attr_value in element["attributes"].items():
                new_node.set(attr_name, attr_value)
            if element.get("children"):
                cls.__create_xml_nodes(new_node, element.get("children"))
            xml_node.append(new_node)

    @classmethod
    def _install(cls):
        """
        Install Peach Fuzzer on the DUT
        """
        peach_archive = wget.download(cls.peach_fuzzer_3_0_url)
        create_directory(cls.base_dir, True)
        TestRun.executor.rsync_to(f"\"{peach_archive}\"", f"{cls.base_dir}")
        TestRun.executor.run_expect_success(
            f'cd {cls.base_dir} && unzip -u "{peach_archive}"')
        if cls._is_installed():
            TestRun.LOGGER.info("Peach fuzzer installed successfully")
            os.remove(peach_archive)
        else:
            TestRun.block("Peach fuzzer installation failed!")

    @classmethod
    def _is_installed(cls):
        """
        Check if Peach Fuzzer is installed on the DUT
        """
        if not cls._is_mono_installed():
            TestRun.block("Mono is not installed, can't continue with Peach Fuzzer!")
        if fs_utils.check_if_directory_exists(posixpath.join(cls.base_dir, cls.peach_dir)):
            return "Peach" in TestRun.executor.run(
                f"cd {cls.base_dir} && {cls.peach_dir}/peach --version").stdout.strip()
        else:
            return False

    @classmethod
    def _escape_special_chars(cls, fuzzed_str: bytes):
        """
        Escape special chars provided in escape_chars list in the fuzzed string generated by
        Peach Fuzzer
        Escaping is done for example in order to make fuzzed string executable in Linux CLI
        If fuzzed string will be used in other places, escape_chars list may be overwritten.
        """
        for i in cls.escape_chars:
            i = bytes(i, "utf-8")
            if i in fuzzed_str[:]:
                fuzzed_str = fuzzed_str.replace(i, b'\\' + i)
        return fuzzed_str

    @classmethod
    def _is_xml_config_prepared(cls):
        """
        Check if Peach Fuzzer XML config is present on the DUT
        """
        if fs_utils.check_if_file_exists(cls.xml_config_file):
            return True
        else:
            return False

    @staticmethod
    def _is_mono_installed():
        """
        Check if Mono (.NET compatible framework) is installed on the DUT
        If it's not, it has to be installed manually.
        For RHEL-based OSes it's usually mono-complete package
        """
        return TestRun.executor.run("which mono").exit_code == 0
