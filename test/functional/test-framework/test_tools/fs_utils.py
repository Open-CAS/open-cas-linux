#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


import base64
import math
import textwrap

from aenum import IntFlag, Enum
from collections import namedtuple
from datetime import datetime

from core.test_run import TestRun
from test_tools.dd import Dd
from test_utils.size import Size, Unit


class Permissions(IntFlag):
    r = 4
    w = 2
    x = 1

    def __str__(self):
        ret_string = ""
        for p in Permissions:
            if p in self:
                ret_string += p.name
        return ret_string


class PermissionsUsers(IntFlag):
    u = 4
    g = 2
    o = 1

    def __str__(self):
        ret_string = ""
        for p in PermissionsUsers:
            if p in self:
                ret_string += p.name
        return ret_string


class PermissionSign(Enum):
    add = '+'
    remove = '-'
    set = '='


class FilesPermissions():
    perms_exceptions = {}

    def __init__(self, files_list: list):
        self.files_list = files_list

    def add_exceptions(self, perms: dict):
        self.perms_exceptions.update(perms)

    def check(self, file_perm: int = 644, dir_perm: int = 755):
        failed_perms = []
        FailedPerm = namedtuple("FailedPerm", ["file", "current_perm", "expected_perm"])

        for file in self.files_list:
            perm = get_permissions(file)

            if file in self.perms_exceptions:
                if perm != self.perms_exceptions[file]:
                    failed_perms.append(FailedPerm(file, perm, self.perms_exceptions[file]))
                continue

            if check_if_regular_file_exists(file):
                if perm != file_perm:
                    failed_perms.append(FailedPerm(file, perm, file_perm))
            elif check_if_directory_exists(file):
                if perm != dir_perm:
                    failed_perms.append(FailedPerm(file, perm, dir_perm))
            else:
                raise Exception(f"{file}: File type not recognized.")

        return failed_perms


def create_directory(path, parents: bool = False):
    cmd = f"mkdir {'--parents ' if parents else ''}\"{path}\""
    return TestRun.executor.run_expect_success(cmd)


def check_if_directory_exists(path):
    return TestRun.executor.run(f"test -d \"{path}\"").exit_code == 0


def check_if_file_exists(path):
    return TestRun.executor.run(f"test -e \"{path}\"").exit_code == 0


def check_if_regular_file_exists(path):
    return TestRun.executor.run(f"test -f \"{path}\"").exit_code == 0


def check_if_symlink_exists(path):
    return TestRun.executor.run(f"test -L \"{path}\"").exit_code == 0


def copy(source: str,
         destination: str,
         force: bool = False,
         recursive: bool = False,
         dereference: bool = False):
    cmd = f"cp{' --force' if force else ''}" \
          f"{' --recursive' if recursive else ''}" \
          f"{' --dereference' if dereference else ''} " \
          f"\"{source}\" \"{destination}\""
    return TestRun.executor.run_expect_success(cmd)


def move(source, destination, force: bool = False):
    cmd = f"mv{' --force' if force else ''} \"{source}\" \"{destination}\""
    return TestRun.executor.run_expect_success(cmd)


def remove(path, force: bool = False, recursive: bool = False, ignore_errors: bool = False):
    cmd = f"rm{' --force' if force else ''}{' --recursive' if recursive else ''} \"{path}\""
    output = TestRun.executor.run(cmd)
    if output.exit_code != 0 and not ignore_errors:
        raise Exception(f"Could not remove file {path}."
                        f"\nstdout: {output.stdout}\nstderr: {output.stderr}")
    return output


def get_permissions(path, dereference: bool = True):
    cmd = f"stat --format='%a' {'--dereference' if dereference else ''} \"{path}\""
    return int(TestRun.executor.run_expect_success(cmd).stdout)


def chmod(path, permissions: Permissions, users: PermissionsUsers,
          sign: PermissionSign = PermissionSign.set, recursive: bool = False):
    cmd = f"chmod{' --recursive' if recursive else ''} " \
          f"{str(users)}{sign.value}{str(permissions)} \"{path}\""
    output = TestRun.executor.run(cmd)
    return output


def chmod_numerical(path, permissions: int, recursive: bool = False):
    cmd = f"chmod{' --recursive' if recursive else ''} {permissions} \"{path}\""
    return TestRun.executor.run_expect_success(cmd)


def chown(path, owner, group, recursive):
    cmd = f"chown {'--recursive ' if recursive else ''}{owner}:{group} \"{path}\""
    return TestRun.executor.run_expect_success(cmd)


def create_file(path):
    if not path.strip():
        raise ValueError("Path cannot be empty or whitespaces.")
    cmd = f"touch \"{path}\""
    return TestRun.executor.run_expect_success(cmd)


def compare(file, other_file):
    output = TestRun.executor.run(
        f"cmp --silent \"{file}\" \"{other_file}\"")
    if output.exit_code == 0:
        return True
    elif output.exit_code > 1:
        raise Exception(f"Compare command execution failed. {output.stdout}\n{output.stderr}")
    else:
        return False


def diff(file, other_file):
    output = TestRun.executor.run(
        f"diff \"{file}\" \"{other_file}\"")
    if output.exit_code == 0:
        return None
    elif output.exit_code > 1:
        raise Exception(f"Diff command execution failed. {output.stdout}\n{output.stderr}")
    else:
        return output.stderr


# For some reason separators other than '/' don't work when using sed on system paths
# This requires escaping '/' in pattern and target string
def escape_sed_string(string: str, sed_replace: bool = False):
    string = string.replace("'", r"\x27").replace("/", r"\/")
    # '&' has special meaning in sed replace and needs to be escaped
    if sed_replace:
        string = string.replace("&", r"\&")
    return string


def insert_line_before_pattern(file, pattern, new_line):
    pattern = escape_sed_string(pattern)
    new_line = escape_sed_string(new_line)
    cmd = f"sed -i '/{pattern}/i {new_line}' \"{file}\""
    return TestRun.executor.run_expect_success(cmd)


def replace_first_pattern_occurrence(file, pattern, new_string):
    pattern = escape_sed_string(pattern)
    new_string = escape_sed_string(new_string, sed_replace=True)
    cmd = f"sed -i '0,/{pattern}/s//{new_string}/' \"{file}\""
    return TestRun.executor.run_expect_success(cmd)


def replace_in_lines(file, pattern, new_string, regexp=False):
    pattern = escape_sed_string(pattern)
    new_string = escape_sed_string(new_string, sed_replace=True)
    cmd = f"sed -i{' -r' if regexp else ''} 's/{pattern}/{new_string}/g' \"{file}\""
    return TestRun.executor.run_expect_success(cmd)


def append_line(file, string):
    cmd = f"echo '{string}' >> \"{file}\""
    return TestRun.executor.run_expect_success(cmd)


def remove_lines(file, pattern, regexp=False):
    pattern = escape_sed_string(pattern)
    cmd = f"sed -i{' -r' if regexp else ''} '/{pattern}/d' \"{file}\""
    return TestRun.executor.run_expect_success(cmd)


def read_file(file):
    if not file.strip():
        raise ValueError("File path cannot be empty or whitespace.")
    output = TestRun.executor.run_expect_success(f"cat \"{file}\"")
    return output.stdout


def write_file(file, content, overwrite: bool = True, unix_line_end: bool = True):
    if not file.strip():
        raise ValueError("File path cannot be empty or whitespace.")
    if not content:
        raise ValueError("Content cannot be empty.")
    if unix_line_end:
        content.replace('\r', '')
    content += '\n'
    max_length = 60000
    split_content = textwrap.TextWrapper(width=max_length, replace_whitespace=False).wrap(content)
    split_content[-1] += '\n'
    for s in split_content:
        redirection_char = '>' if overwrite else '>>'
        overwrite = False
        encoded_content = base64.b64encode(s.encode("utf-8"))
        cmd = f"printf '{encoded_content.decode('utf-8')}' " \
              f"| base64 --decode {redirection_char} \"{file}\""
        TestRun.executor.run_expect_success(cmd)


def uncompress_archive(file, destination=None):
    from test_utils.filesystem.file import File

    if not isinstance(file, File):
        file = File(file)
    if not destination:
        destination = file.parent_dir
    command = (f"unzip -u {file.full_path} -d {destination}"
               if str(file).endswith(".zip")
               else f"tar --extract --file={file.full_path} --directory={destination}")
    TestRun.executor.run_expect_success(command)


def ls(path, options=''):
    default_options = "-lA --time-style=+'%Y-%m-%d %H:%M:%S'"
    output = TestRun.executor.run(
        f"ls {default_options} {options} \"{path}\"")
    return output.stdout


def ls_item(path):
    output = ls(path, '-d')
    return output.splitlines()[0] if output else None


def parse_ls_output(ls_output, dir_path=''):
    split_output = ls_output.split('\n')
    fs_items = []
    for line in split_output:
        if not line.strip():
            continue
        line_fields = line.split()
        if len(line_fields) < 8:
            continue
        file_type = line[0]
        if file_type not in ['-', 'd', 'l', 'b', 'c', 'p', 's']:
            continue
        permissions = line_fields[0][1:].replace('.', '')
        owner = line_fields[2]
        group = line_fields[3]
        has_size = ',' not in line_fields[4]
        if has_size:
            size = Size(float(line_fields[4]), Unit.Byte)
        else:
            size = None
            line_fields.pop(4)
        split_date = line_fields[5].split('-')
        split_time = line_fields[6].split(':')
        modification_time = datetime(int(split_date[0]), int(split_date[1]), int(split_date[2]),
                                     int(split_time[0]), int(split_time[1]), int(split_time[2]))
        if dir_path and file_type != 'l':
            full_path = '/'.join([dir_path, line_fields[7]])
        else:
            full_path = line_fields[7]

        from test_utils.filesystem.file import File, FsItem
        from test_utils.filesystem.directory import Directory
        from test_utils.filesystem.symlink import Symlink

        if file_type == '-':
            fs_item = File(full_path)
        elif file_type == 'd':
            fs_item = Directory(full_path)
        elif file_type == 'l':
            fs_item = Symlink(full_path)
        else:
            fs_item = FsItem(full_path)

        fs_item.permissions.user = Permissions['|'.join(list(permissions[:3].replace('-', '')))] \
            if permissions[:3] != '---' else Permissions(0)
        fs_item.permissions.group = Permissions['|'.join(list(permissions[3:6].replace('-', '')))] \
            if permissions[3:6] != '---' else Permissions(0)
        fs_item.permissions.other = Permissions['|'.join(list(permissions[6:].replace('-', '')))] \
            if permissions[6:] != '---' else Permissions(0)

        fs_item.owner = owner
        fs_item.group = group
        fs_item.size = size
        fs_item.modification_time = modification_time
        fs_items.append(fs_item)
    return fs_items


def find_all_files(path: str, recursive: bool = True):
    if not path.strip():
        raise ValueError("No path given.")

    output = TestRun.executor.run_expect_success(f"find \"{path}\" {'-maxdepth 1' if not recursive else ''} \( -type f -o -type l \) -print")

    return output.stdout.splitlines()


def find_all_dirs(path: str, recursive: bool = True):
    if not path.strip():
        raise ValueError("No path given.")

    output = TestRun.executor.run_expect_success(f"find \"{path}\" {'-maxdepth 1' if not recursive else ''} -type d -print")

    return output.stdout.splitlines()


def find_all_items(path: str, recursive: bool = True):
    return [*find_all_files(path, recursive), *find_all_dirs(path, recursive)]


def readlink(link: str, options="--canonicalize-existing"):
    return TestRun.executor.run_expect_success(
        f"readlink {options} \"{link}\""
    ).stdout


def create_random_test_file(target_file_path: str,
                            file_size: Size = Size(1, Unit.MebiByte),
                            random: bool = True):
    from test_utils.filesystem.file import File
    bs = Size(512, Unit.KibiByte)
    cnt = math.ceil(file_size.value / bs.value)
    file = File.create_file(target_file_path)
    dd = Dd().output(target_file_path) \
             .input("/dev/urandom" if random else "/dev/zero") \
             .block_size(bs) \
             .count(cnt) \
             .oflag("direct")
    dd.run()
    file.refresh_item()
    return file
