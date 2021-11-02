#!/usr/bin/env python3
#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import argparse
import enum
import glob
import io
import markdown
import os
import sys
import yaml
import yaml.scanner


def error(filename, line, column, string):
    string = "\n        ".join(string.split('\n'))
    print(f"[ERROR] {filename}: line {line}, column {column}: {string}", file=sys.stderr)
    exit(1)


class Entity:
    def __init__(self):
        self.header_text = ""
        self.header = None
        self.text = ""


class State(enum.Enum):
    BEGIN = enum.auto()
    GROUP_HEADER = enum.auto()
    GROUP_TEXT = enum.auto()
    REQ_HEADER_PRE = enum.auto()
    REQ_HEADER = enum.auto()
    REQ_TEXT = enum.auto()


def parse_header(entity, filename, line):
    try:
        entity.header = yaml.safe_load(entity.header_text)
    except yaml.scanner.ScannerError as e:
        error(filename, line+e.problem_mark.line+1,
                e.problem_mark.column+1, f"{e.context}\n{e.problem}")


def parse_file(filename):
    state = State.BEGIN
    group = None
    reqs = []
    current_entity = None
    header_line = 0
    with open(filename, "r") as f:
        for i, l in enumerate(f.readlines(), start=1):
            if l.strip() == "---":
                if state == State.BEGIN:
                    current_entity = Entity()
                    state = State.GROUP_HEADER
                    header_line = i
                elif state == State.GROUP_HEADER:
                    parse_header(current_entity, filename, header_line)
                    state = State.GROUP_TEXT
                elif state == State.GROUP_TEXT:
                    error(filename, i, 1, "unexpected \"---\",\n"
                            "expected markdown or req header marker")
                elif state == State.REQ_HEADER_PRE:
                    error(filename, i, 1, "unexpected \"---\",\n"
                            "expected another line of req header marker")
                elif state == State.REQ_HEADER:
                    parse_header(current_entity, filename, header_line)
                    state = State.REQ_TEXT
                elif state == State.REQ_TEXT:
                    error(filename, i, 1, "unexpected \"---\",\n"
                            "expected markdown or next req header marker")
                else:
                    error(filename, i, 1, "something went terribly wrong")
            elif l.strip() == "-"*80:
                if state == State.BEGIN:
                    error(filename, i, 1, "unexpected req header marker,\n"
                            "expected group header marker")
                elif state == State.GROUP_HEADER:
                    error(filename, i, 1, "unexpected req header marker,\n"
                            "expected yaml or group header end marker")
                elif state == State.GROUP_TEXT:
                    group = current_entity
                    current_entity = None
                    state = State.REQ_HEADER_PRE
                elif state == State.REQ_HEADER_PRE:
                    current_entity = Entity()
                    state = State.REQ_HEADER
                    header_line = i
                elif state == State.REQ_HEADER:
                    error(filename, i, 1, "unexpected req header marker,\n"
                            "expected markdown or req header end marker")
                elif state == State.REQ_TEXT:
                    reqs.append(current_entity)
                    current_entity = None
                    state = State.REQ_HEADER_PRE
                else:
                    error(filename, i, 1, "something went terribly wrong")
            else:
                if state == State.BEGIN:
                    error(filename, i, 1, "unexpected character, expected group header")
                elif state == State.GROUP_HEADER:
                    current_entity.header_text += l
                elif state == State.GROUP_TEXT:
                    current_entity.text += l
                elif state == State.REQ_HEADER_PRE:
                    error(filename, i, 1, "expected another line of req header marker")
                elif state == State.REQ_HEADER:
                    current_entity.header_text += l
                elif state == State.REQ_TEXT:
                    current_entity.text += l
                else:
                    error(filename, i, 1, "something went terribly wrong")
    if state == State.REQ_TEXT:
            reqs.append(current_entity)
    return (group, reqs)


parser = argparse.ArgumentParser(prog="reqparse")
parser.add_argument(
    "-o", "--output", action="store",
    help="Output file"
)
parser.add_argument(
    "-f", "--format", action="store",
    choices=["html", "markdown"], default="markdown",
    help="Output format {html|markdown}",
)

args = parser.parse_args(sys.argv[1:])

buf = ""
with io.StringIO() as output:
    for filename in glob.glob("requirements/*"):
        group, reqs = parse_file(filename)
        output.write(f"# {group.header['group']}\n")
        output.write(group.text)
        for r in reqs:
            output.write(f"## {r.header['title']}\n")
            output.write(r.text)
    buf = output.getvalue()

if args.format == "html":
    buf = markdown.markdown(buf, extensions=['sane_lists'])

if args.output:
    with open(args.output, "w+") as outfile:
        outfile.write(buf)
else:
    print(buf)
