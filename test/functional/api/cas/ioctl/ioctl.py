#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import ctypes
import marshal
import os
from time import sleep

from core.test_run import TestRun
from test_tools.fs_utils import chmod_numerical, remove, check_if_directory_exists, \
    create_directory

IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_DIRBITS = 2

IOC_NRMASK = (1 << IOC_NRBITS) - 1                  # 255
IOC_TYPEMASK = (1 << IOC_TYPEBITS) - 1              # 255
IOC_SIZEMASK = (1 << IOC_SIZEBITS) - 1              # 16 383
IOC_DIRMASK = (1 << IOC_DIRBITS) - 1                # 3

IOC_NRSHIFT = 0                                     # 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS            # 8
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS        # 16
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS         # 30

IOC_NONE = 0
IOC_WRITE = 1
IOC_READ = 2

KCAS_IOCTL_MAGIC = 0xBA                             # 186

IOC_IN = IOC_WRITE << IOC_DIRSHIFT                  # 1 073 741 824
IOC_OUT = IOC_READ << IOC_DIRSHIFT                  # 2 147 483 648
IOC_INOUT = (IOC_WRITE | IOC_READ) << IOC_DIRSHIFT  # 3 221 225 472
IOCSIZE_MASK = IOC_SIZEMASK << IOC_SIZESHIFT        # 1 073 676 288
IOCSIZE_SHIFT = IOC_SIZESHIFT                       # 16


def IOC(dir, type, nr, size):
    if dir > IOC_DIRMASK:
        raise OverflowError(f"IO direction value {dir} exceeds {IOC_DIRMASK}")
    dir <<= IOC_DIRSHIFT

    if type > IOC_TYPEMASK:
        raise OverflowError(f"IO type value {type} exceeds {IOC_TYPEMASK}")
    type <<= IOC_TYPESHIFT

    if nr > IOC_NRMASK:
        raise OverflowError(f"IO command value {nr} exceeds {IOC_NRMASK}")
    nr <<= IOC_NRSHIFT

    if size > IOC_SIZEMASK:
        raise OverflowError(f"IO size value {size} exceeds {IOC_SIZEMASK}")
    size <<= IOC_SIZESHIFT

    return dir | type | nr | size


def IOC_TYPECHECK(item):
    return ctypes.sizeof(item)


def IO(nr):
    return IOC(IOC_NONE, KCAS_IOCTL_MAGIC, nr, 0)


def IOR(nr, size):
    return IOC(IOC_READ, KCAS_IOCTL_MAGIC, nr, IOC_TYPECHECK(size))


def IOW(nr, size):
    return IOC(IOC_WRITE, KCAS_IOCTL_MAGIC, nr, IOC_TYPECHECK(size))


def IOWR(nr, size):
    return IOC(IOC_READ | IOC_WRITE, KCAS_IOCTL_MAGIC, nr, IOC_TYPECHECK(size))


def IOR_BAD(nr, size):
    return IOC(IOC_READ, KCAS_IOCTL_MAGIC, nr, ctypes.sizeof(size))


def IOW_BAD(nr, size):
    return IOC(IOC_WRITE, KCAS_IOCTL_MAGIC, nr, ctypes.sizeof(size))


def IOWR_BAD(nr, size):
    return IOC(IOC_READ | IOC_WRITE, KCAS_IOCTL_MAGIC, nr, ctypes.sizeof(size))


def IOC_DIR(nr):
    return (nr >> IOC_DIRSHIFT) & IOC_DIRMASK


def IOC_TYPE(nr):
    return (nr >> IOC_TYPESHIFT) & IOC_TYPEMASK


def IOC_NR(nr):
    return (nr >> IOC_NRSHIFT) & IOC_NRMASK


def IOC_SIZE(nr):
    return (nr >> IOC_SIZESHIFT) & IOC_SIZEMASK


temp_dir = '/tmp/cas'
struct_path = os.path.join(temp_dir, 'dump_file')
script_source = os.path.join(f'{os.path.dirname(__file__)}', 'send_ioctl_script.py')
script_dest = os.path.join(temp_dir, 'send_ioctl_script.py')


def send_script_with_dumped_args():
    if not check_if_directory_exists(temp_dir):
        create_directory(temp_dir, True)

    TestRun.executor.rsync_to(script_source, script_dest)
    chmod_numerical(script_dest, 550)

    TestRun.executor.rsync_to(struct_path, struct_path)
    chmod_numerical(struct_path, 440)


def cas_ioctl(cas_ioctl_request, interrupt: bool = False):
    if not os.path.exists(temp_dir):
        os.mkdir(temp_dir)

    with open(struct_path, 'wb') as dump_file:
        marshal.dump(cas_ioctl_request.command_struct, dump_file)

    send_script_with_dumped_args()
    if interrupt:
        pid = TestRun.executor.run_in_background(
            f"{script_dest} -c {cas_ioctl_request.command} -s {struct_path}"
        )
        sleep(2)
        TestRun.executor.kill_process(pid)
    else:
        TestRun.executor.run(f"{script_dest} -c {cas_ioctl_request.command} -s {struct_path}")
    if check_if_directory_exists(temp_dir):
        remove(temp_dir, True, True, True)
    if os.path.exists(struct_path):
        os.remove(struct_path)
