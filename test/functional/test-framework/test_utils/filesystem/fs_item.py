#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath

from test_tools import fs_utils


class FsItem:
    def __init__(self, full_path):
        self.full_path = full_path
        # all below values must be refreshed in refresh_item()
        self.parent_dir = self.get_parent_dir(self.full_path)
        self.name = self.get_name(self.full_path)
        self.modification_time = None
        self.owner = None
        self.group = None
        self.permissions = FsPermissions()
        self.size = None

    @staticmethod
    def get_name(path):
        head, tail = posixpath.split(path)
        return tail or posixpath.basename(head)

    @staticmethod
    def get_parent_dir(path):
        head, tail = posixpath.split(path)
        if tail:
            return head
        else:
            head, tail = posixpath.split(head)
            return head

    def __str__(self):
        return self.full_path

    def chmod_numerical(self, permissions: int, recursive: bool = False):
        fs_utils.chmod_numerical(self.full_path, permissions, recursive)
        self.refresh_item()

    def chmod(self,
              permissions: fs_utils.Permissions,
              users: fs_utils.PermissionsUsers,
              sign: fs_utils.PermissionSign = fs_utils.PermissionSign.set,
              recursive: bool = False):
        fs_utils.chmod(self.full_path, permissions, users, sign=sign, recursive=recursive)
        self.refresh_item()

    def chown(self, owner, group, recursive: bool = False):
        fs_utils.chown(self.full_path, owner, group, recursive)
        self.refresh_item()

    def copy(self,
             destination,
             force: bool = False,
             recursive: bool = False,
             dereference: bool = False):
        target_dir_exists = fs_utils.check_if_directory_exists(destination)
        fs_utils.copy(str(self), destination, force, recursive, dereference)
        if target_dir_exists:
            path = f"{destination}{'/' if destination[-1] != '/' else ''}{self.name}"
        else:
            path = destination
        output = fs_utils.ls_item(f"{path}")
        return fs_utils.parse_ls_output(output)[0]

    def move(self,
             destination,
             force: bool = False):
        target_dir_exists = fs_utils.check_if_directory_exists(destination)
        fs_utils.move(str(self), destination, force)
        if target_dir_exists:
            self.full_path = f"{destination}{'/' if destination[-1] != '/' else ''}{self.name}"
        else:
            self.full_path = destination
        self.refresh_item()
        return self

    def refresh_item(self):
        updated_file = fs_utils.parse_ls_output(fs_utils.ls_item(self.full_path))[0]
        # keep order the same as in __init__()
        self.parent_dir = updated_file.parent_dir
        self.name = updated_file.name
        self.modification_time = updated_file.modification_time
        self.owner = updated_file.owner
        self.group = updated_file.group
        self.permissions = updated_file.permissions
        self.size = updated_file.size
        return self


class FsPermissions:
    def __init__(self, user=None, group=None, other=None):
        self.user = user
        self.group = group
        self.other = other

    def __eq__(self, other):
        return self.user == other.user and self.group == other.group and self.other == other.other
