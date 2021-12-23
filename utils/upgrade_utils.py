#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import logging
import subprocess
import os
import re


def user_prompt(message, choices, default):
    result = None
    prompt = f"{message} ({'/'.join(choices)})[{default}]: "
    logging.info(f"Prompting user: {prompt}")
    while result not in choices:
        result = input(f"\n{prompt}")
        if not result:
            logging.info(f"User chose default: {default}")
            result = default
        else:
            logging.info(f"User chose: {result}")

    return result


def yn_prompt(message, default="n"):
    return user_prompt(message, choices=["y", "n"], default=default)


class Result:
    def __init__(self, msg=""):
        self.msg = msg

    def __str__(self):
        return f"{type(self).__name__}: {self.msg}"


class Failure(Result):
    def result_mark(self):
        return "[\u001b[31mX\u001b[0m]"


class Success(Result):
    def result_mark(self):
        return "[\u001b[32mv\u001b[0m]"


class Warn(Result):
    def result_mark(self):
        return "[\u001b[33m!\u001b[0m]"


class Except(Failure):
    def result_mark(self):
        return "[\u001b[31mE\u001b[0m]"


class Abort(Failure):
    def result_mark(self):
        return "[\u001b[31mA\u001b[0m]"


class StateMachine:
    transition_map = {}

    def __init__(self, initial_state, **args):
        self.initial_state = initial_state
        self.params = args

    def run(self):
        s = self.initial_state
        result = Success()
        self.last_fail = None
        try:
            while s is not None:
                self.current_state = s(self)

                result = self.current_state.start()
                if isinstance(result, Failure):
                    self.last_fail = result

                try:
                    s = self.transition_map[s][type(result)]
                except KeyError:
                    try:
                        s = self.transition_map[s]["default"]
                    except KeyError:
                        s = self.transition_map["default"]
        except KeyboardInterrupt:
            self.result = self.abort()
        except Exception as e:
            self.result = self.exception(f"{type(e).__name__}({e})")

        if self.last_fail:
            result = self.last_fail

        logging.info(f"Finishing {type(self).__name__} with result {result}")
        return result

    def abort(self):
        log = "User interrupted"
        print(log)
        logging.warning(log)

        return Abort()

    def exception(self, e):
        log = f"Stopping {type(self).__name__}. Reason: {e}"
        print(log)
        self.last_fail = Except(e)
        logging.exception(log)

        return self.last_fail


class UpgradeState:
    will_prompt = False
    log = ""

    def __init__(self, sm):
        self.state_machine = sm

    def do_work(self):
        raise NotImplementedError()

    def start(self):
        self.enter_state()
        try:
            self.result = self.do_work()
        except KeyboardInterrupt:
            self.result = Abort("User aborted")
        except Exception as e:
            log = f"State {type(self).__name__} failed unexpectedly. Reason: {e}"
            self.result = Except(log)
            logging.exception(log)
            raise e

        self.exit_state()

        return self.result

    def enter_state(self):
        logging.debug(f"Entering state {type(self).__name__}")
        print(f"{self.log+'...':60}", end="", flush=True)

    def exit_state(self):
        if isinstance(self.result, Success):
            log = logging.debug
        elif isinstance(self.result, Warn):
            log = logging.warning
        else:
            log = logging.error

        log(f"Exiting state {type(self).__name__} with result '{self.result}'")
        if self.will_prompt:
            print(f"\n{self.log+'...':60}", end="", flush=True)

        print(self.result.result_mark())


def insert_module(name, installed=True, **params):
    cmd_params = [f"{param}={val}" for param, val in params.items()]

    cmd = ["modprobe", "--first-time"] if installed else ["insmod"]
    cmd += [name] + cmd_params

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if p.returncode:
        raise Exception(p.stderr.decode("ascii").rstrip("\n"))


def remove_module(name):
    p = subprocess.run(["rmmod", name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if p.returncode:
        raise Exception(p.stderr.decode("ascii").rstrip("\n"))


def get_device_sysfs_path(device):
    basename = os.path.basename(device)

    p1 = subprocess.Popen(["find", "-L", "/sys/block", "-maxdepth", "2"], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep", f"{basename}$"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p3 = subprocess.Popen(
        ["sed", "-r", "s/(\/sys\/block\/[^/]+).*/\\1/"], stdin=p2.stdout, stdout=subprocess.PIPE
    )  # noqa W605
    p1.stdout.close()
    p2.stdout.close()

    output = p3.communicate()[0]

    return output.decode("ascii").rstrip("\n")


def get_device_schedulers(sysfs_path):
    with open(f"{sysfs_path}/queue/scheduler", "r") as f:
        schedulers = f.readline().rstrip("\n")

    try:
        current = re.match(".*\[(.*)\].*", schedulers)[1]  # noqa W605
    except IndexError:
        current = "none"
        pass

    available = schedulers.replace("[", "").replace("]", "").split()

    return current, available


def set_device_scheduler(sysfs_path, scheduler):
    with open(f"{sysfs_path}/queue/scheduler", "w") as f:
        f.write(f"{scheduler}\n")


def drop_os_caches():
    with open(f"/proc/sys/vm/drop_caches", "w") as f:
        f.write("3")
