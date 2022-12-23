#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from collections import defaultdict


class LinuxCommand:
    def __init__(self, command_executor, command_name):
        self.command_executor = command_executor
        self.command_param = defaultdict(list)
        self.command_flags = []
        self.command_name = command_name
        self.param_name_prefix = ''
        self.param_separator = ' '
        self.param_value_prefix = '='
        self.param_value_list_separator = ','
        self.command_env_var = defaultdict(list)
        self.env_var_separator = ' '
        self.env_var_value_prefix = '='

    def run(self):
        return self.command_executor.run(str(self))

    def run_in_background(self):
        return self.command_executor.run_in_background(str(self))

    def set_flags(self, *flag):
        for f in flag:
            self.command_flags.append(f)
        return self

    def remove_flag(self, flag):
        if flag in self.command_flags:
            self.command_flags.remove(flag)
        return self

    def set_param(self, key, *values):
        self.remove_param(key)

        for val in values:
            self.command_param[key].append(str(val))
        return self

    def remove_param(self, key):
        if key in self.command_param:
            del self.command_param[key]
        return self

    def set_env_var(self, key, *values):
        self.remove_env_var(key)

        for val in values:
            self.command_env_var[key].append(str(val))
        return self

    def remove_env_var(self, key):
        if key in self.command_env_var:
            del self.command_env_var[key]
        return self

    def get_parameter_value(self, param_name):
        if param_name in self.command_param.keys():
            return self.command_param[param_name]
        return None

    def __str__(self):
        command = ''
        for key, value in self.command_env_var.items():
            command += f'{key}{self.env_var_value_prefix}{",".join(value)}' \
                       f'{self.env_var_separator}'
        command += self.command_name
        for key, value in self.command_param.items():
            command += f'{self.param_separator}{self.param_name_prefix}' \
                f'{key}{self.param_value_prefix}{",".join(value)}'
        for flag in self.command_flags:
            command += f'{self.param_separator}{self.param_name_prefix}{flag}'
        return command
