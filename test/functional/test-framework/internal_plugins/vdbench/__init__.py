#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time
import posixpath

from datetime import timedelta
from core.test_run import TestRun
from test_tools import fs_utils


class Vdbench:
    def __init__(self, params, config):
        print("VDBench plugin initialization")
        self.run_time = timedelta(seconds=60)

        try:
            self.working_dir = config["working_dir"]
            self.reinstall = config["reinstall"]
            self.source_dir = config["source_dir"]
        except Exception:
            raise Exception("Missing fields in config! ('working_dir', 'source_dir' and "
                            "'reinstall' required)")

        self.result_dir = posixpath.join(self.working_dir, 'result.tod')

    def pre_setup(self):
        pass

    def post_setup(self):
        print("VDBench plugin post setup")
        if not self.reinstall and fs_utils.check_if_directory_exists(self.working_dir):
            return

        if fs_utils.check_if_directory_exists(self.working_dir):
            fs_utils.remove(self.working_dir, True, True)

        fs_utils.create_directory(self.working_dir)
        TestRun.LOGGER.info("Copying vdbench to working dir.")
        fs_utils.copy(posixpath.join(self.source_dir, "*"), self.working_dir,
                      True, True)
        pass

    def teardown(self):
        pass

    def create_config(self, config, run_time: timedelta):
        self.run_time = run_time
        if config[-1] != ",":
            config += ","
        config += f"elapsed={int(run_time.total_seconds())}"
        TestRun.LOGGER.info(f"Vdbench config:\n{config}")
        fs_utils.write_file(posixpath.join(self.working_dir, "param.ini"), config)

    def run(self):
        cmd = f"{posixpath.join(self.working_dir, 'vdbench')} " \
              f"-f {posixpath.join(self.working_dir, 'param.ini')} " \
              f"-vr -o {self.result_dir}"
        full_cmd = f"screen -dmS vdbench {cmd}"
        TestRun.executor.run(full_cmd)
        start_time = time.time()

        timeout = self.run_time * 1.5

        while True:
            if not TestRun.executor.run(f"ps aux | grep '{cmd}' | grep -v grep").exit_code == 0:
                return self.analyze_log()

            if time.time() - start_time > timeout.total_seconds():
                TestRun.LOGGER.error("Vdbench timeout.")
                return False
            time.sleep(1)

    def analyze_log(self):
        output = TestRun.executor.run(
            f"ls -1td {self.result_dir[0:len(self.result_dir) - 3]}* | head -1")
        log_path = posixpath.join(output.stdout if output.exit_code == 0 else self.result_dir,
                                "logfile.html")

        log_file = fs_utils.read_file(log_path)

        if "Vdbench execution completed successfully" in log_file:
            TestRun.LOGGER.info("Vdbench execution completed successfully.")
            return True

        if "Data Validation error" in log_file or "data_errors=1" in log_file:
            TestRun.LOGGER.error("Data corruption occurred!")
        elif "Heartbeat monitor:" in log_file:
            TestRun.LOGGER.error("Vdbench: heartbeat.")
        else:
            TestRun.LOGGER.error("Vdbench unknown result.")
        return False


plugin_class = Vdbench
