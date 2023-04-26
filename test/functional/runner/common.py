#
# Copyright(c) 2023 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from contextlib import contextmanager
from datetime import timedelta
from filelock import FileLock
from json.decoder import JSONDecodeError
import hashlib
import json
import os
import random
import re
import sys
import time
import yaml


meta_lock = FileLock("meta/runner.lock")


class ConfigFile:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.last_modify = 0

    def __access(self):
        self.last_modify = os.path.getmtime(self.path)

    def need_reload(self):
        return self.last_modify != os.path.getmtime(self.path)

    def load(self):
        with meta_lock:
            self.__access()
            with open(self.path, 'r') as conf:
                return yaml.safe_load(conf)

    def save(self, data):
        with meta_lock:
            self.__access()
            with open(self.path, 'w') as conf:
                return yaml.dump(data, conf)


class JournalFile:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.last_modify = 0

    def __access(self):
        self.last_modify = os.path.getmtime(self.path)

    def create(self):
        with self.record():
            pass

    def need_reload(self):
        if not os.path.isfile(self.path):
            return False
        return self.last_modify != os.path.getmtime(self.path)

    def load(self):
        with meta_lock:
            if not os.path.isfile(self.path):
                return []
            self.__access()
            with open(self.path, 'r') as journal_file:
                return json.load(journal_file)

    @contextmanager
    def record(self):
        with meta_lock:
            with open(self.path, 'a+') as journal_file:
                self.__access()
                try:
                    journal_file.seek(0)
                    journal = json.load(journal_file)
                except JSONDecodeError:
                    journal = []
                new_entries = []
                yield new_entries
                journal.extend(new_entries)
                journal_file.truncate(0)
                json.dump(journal, journal_file)


class StatusFile:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    def create(self):
        with self.edit():
            pass

    def load(self):
        with meta_lock:
            if not os.path.isfile(self.path):
                return {}
            with open(self.path, 'r') as status_file:
                return json.load(status_file)

    @contextmanager
    def edit(self):
        with meta_lock:
            with open(self.path, 'a+') as status_file:
                try:
                    status_file.seek(0)
                    status = json.load(status_file)
                except JSONDecodeError:
                    status = {}
                yield status
                status_file.truncate(0)
                json.dump(status, status_file)


class TestCase(dict):
    def __init__(self, data):
        super().__init__(data)
        if 'sha' not in self:
            signature = self.signature().encode("UTF-8")
            self['sha'] = hashlib.sha1(signature).hexdigest().upper()

    def signature(self):
        return f"{self['dir']}|{self}|{self['seed']}"

    def function(self):
        if self['params']:
            return f"{self['name']}[{self['params']}]"
        else:
            return f"{self['name']}"

    def test(self):
        return f"{self['path']}::{self.function()}"

    def __hash__(self):
        return hash(self.signature())

    def __eq__(self, other):
        return self.signature() == other.signature()

    def __repr__(self):
        return self.test()

    def __str__(self):
        return self.test()

    @classmethod
    def from_canonical_name(cls, directory, canon_name, seed, pytest_options):
        m = re.fullmatch(r'(\S+)::([^\[]+)\[?([^\]]+)?\]?', canon_name)
        path, name, params = m.groups()
        return cls({
            'dir': directory,
            'path': path,
            'name': name,
            'params': params,
            'seed': seed,
            'pytest-options': pytest_options
        })


class TestEvent(dict):
    def __init__(self, data):
        super().__init__(data)
        self['test-case'] = TestCase(self['test-case'])

    def signature(self):
        return f"{self['test-case'].signature()}|{self['sha']}"

    def duration(self):
        try:
            start_time = self['start-timestamp']
            end_time = self.get('end-timestamp', time.time())
            return timedelta(seconds=int(end_time-start_time))
        except:
            return timedelta(0)

    def __eq__(self, other):
        return self.signature() == other.signature()

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f"<{self['sha']}>{self['test-case']}"

    @classmethod
    def new(cls, test_case, data={}):
        signature = f"{test_case.signature()}{time.time()}".encode("UTF-8")
        return cls({
            **{
                'test-case': test_case,
                'sha': hashlib.sha1(signature).hexdigest()
            },
            **data
        })

class JournalParser:
    def __init__(self, journal_file):
        self.journal_file = journal_file

    def parse(self):
        journal_dict = {}
        for entry in self.journal_file.load():
            test_event = TestEvent(entry['test-event'])
            if entry['type'] == "add":
                journal_dict[test_event['sha']] = test_event
            elif entry['type'] == "delete":
                del journal_dict[test_event['sha']]
        return list(journal_dict.values())
