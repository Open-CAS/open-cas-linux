#!/usr/bin/env python3
#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause-Clear
#

import argparse
import marshal
import os
import sys
from fcntl import ioctl


def main():
    CAS_DEVICE = '/dev/cas_ctrl'

    parser = argparse.ArgumentParser(description=f'Send ioctl request to {CAS_DEVICE}')

    parser.add_argument('-c', '--command', action='store', dest='command', type=str,
                        required=True, help=f"Specific request code to send to {CAS_DEVICE}")
    parser.add_argument('-s', '--struct', action='store', dest='struct', type=str,
                        required=True, help="Structure of CAS request")
    args = parser.parse_args()

    with open(args.struct, 'rb') as struct_file:
        struct = bytearray(marshal.load(struct_file))

    fd = os.open(CAS_DEVICE, os.O_RDWR)
    try:
        ioctl(fd, int(args.command), struct)
    except OSError as err:
        print(f"IOCTL request returned error: {err}", sys.stdout)
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
