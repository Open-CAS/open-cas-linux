#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from core.test_run import TestRun
from test_tools.fs_utils import (
    readlink,
    create_directory,
    check_if_symlink_exists,
    check_if_directory_exists,
)
from test_utils.filesystem.file import File


class Symlink(File):
    def __init__(self, full_path):
        File.__init__(self, full_path)

    def md5sum(self, binary=True):
        output = TestRun.executor.run_expect_success(
            f"md5sum {'-b' if binary else ''} {self.get_target()}"
        )
        return output.stdout.split()[0]

    def get_target(self):
        return readlink(self.full_path)

    def get_symlink_path(self):
        return self.full_path

    def remove_symlink(self):
        path = self.get_symlink_path()
        TestRun.executor.run_expect_success(f"rm -f {path}")

    @classmethod
    def create_symlink(cls, link_path: str, target: str, force: bool = False):
        """
         Creates a Symlink - new or overwrites existing one if force parameter is True
         :param link_path: path to the place where we want to create a symlink
         :param target: the path of an object that the requested Symlink points to
         :param force: determines if the existing symlink with the same name should be overridden
         return: Symlink object located under link_path
        """
        cmd = f"ln --symbolic {target} {link_path}"
        is_dir = check_if_directory_exists(link_path)
        parent_dir = cls.get_parent_dir(link_path)
        if is_dir:
            raise IsADirectoryError(f"'{link_path}' is an existing directory.")
        if force:
            if not check_if_directory_exists(parent_dir):
                create_directory(parent_dir, True)
            TestRun.executor.run_expect_success(f"rm -f {link_path}")
        TestRun.executor.run_expect_success(cmd)
        return cls(link_path)

    @classmethod
    def get_symlink(cls, link_path: str, target: str = None, create: bool = False):
        """
        Request a Symlink (create new or identify existing)
        :param link_path: full path of the requested Symlink
        :param target: path of an object that the requested Symlink points to
                       (required if create is True)
        :param create: determines if the requested Symlink should be created if it does not exist
        :return: Symlink object located under link_path
        """
        if create and not target:
            raise AttributeError("Target is required for symlink creation.")

        is_symlink = check_if_symlink_exists(link_path)
        if is_symlink:
            if not target or readlink(link_path) == readlink(target):
                return cls(link_path)
            else:
                raise FileExistsError("Existing symlink points to a different target.")
        elif not create:
            raise FileNotFoundError("Requested symlink does not exist.")

        is_dir = check_if_directory_exists(link_path)
        if is_dir:
            raise IsADirectoryError(
                f"'{link_path}' is an existing directory." "\nUse a full path for symlink creation."
            )

        parent_dir = cls.get_parent_dir(link_path)
        if not check_if_directory_exists(parent_dir):
            create_directory(parent_dir, True)

        cmd = f"ln --symbolic {target} {link_path}"
        TestRun.executor.run_expect_success(cmd)
        return cls(link_path)
