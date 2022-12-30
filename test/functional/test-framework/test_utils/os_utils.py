#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import math
import posixpath
import re
import time
from datetime import timedelta, datetime

from aenum import IntFlag, Enum, IntEnum
from packaging import version

from core.test_run import TestRun
from storage_devices.device import Device
from test_tools.dd import Dd
from test_tools.disk_utils import get_sysfs_path
from test_tools.fs_utils import check_if_directory_exists, create_directory, check_if_file_exists
from test_utils.filesystem.file import File
from test_utils.output import CmdException
from test_utils.retry import Retry
from test_utils.size import Size, Unit

DEBUGFS_MOUNT_POINT = "/sys/kernel/debug"
MEMORY_MOUNT_POINT = "/mnt/memspace"


class DropCachesMode(IntFlag):
    PAGECACHE = 1
    SLAB = 2
    ALL = PAGECACHE | SLAB


class OvercommitMemoryMode(Enum):
    DEFAULT = 0
    ALWAYS = 1
    NEVER = 2


class Runlevel(IntEnum):
    """
        Halt the system.
        SysV Runlevel: 0
        systemd Target: runlevel0.target, poweroff.target
    """
    runlevel0 = 0
    poweroff = runlevel0

    """
        Single user mode.
        SysV Runlevel: 1, s, single
        systemd Target: runlevel1.target, rescue.target
    """
    runlevel1 = 1
    rescue = runlevel1

    """
        User-defined/Site-specific runlevels. By default, identical to 3.
        SysV Runlevel: 2, 4
        systemd Target: runlevel2.target, runlevel4.target, multi-user.target
    """
    runlevel2 = 2

    """
        Multi-user, non-graphical. Users can usually login via multiple consoles or via the network.
        SysV Runlevel: 3
        systemd Target: runlevel3.target, multi-user.target
    """
    runlevel3 = 3
    multi_user = runlevel3

    """
        Multi-user, graphical. Usually has all the services of runlevel 3 plus a graphical login.
        SysV Runlevel: 5
        systemd Target: runlevel5.target, graphical.target
    """
    runlevel5 = 5
    graphical = runlevel5

    """
        Reboot
        SysV Runlevel: 6
        systemd Target: runlevel6.target, reboot.target
    """
    runlevel6 = 6
    reboot = runlevel6

    """
        Emergency shell
        SysV Runlevel: emergency
        systemd Target: emergency.target
    """
    runlevel7 = 7
    emergency = runlevel7


class SystemManagerType(Enum):
    sysv = 0
    systemd = 1


def get_system_manager():
    output = TestRun.executor.run_expect_success("ps -p 1").stdout
    type = output.split('\n')[1].split()[3]
    if type == "init":
        return SystemManagerType.sysv
    elif type == "systemd":
        return SystemManagerType.systemd
    raise Exception(f"Unknown system manager type ({type}).")


def change_runlevel(runlevel: Runlevel):
    if runlevel == get_runlevel():
        return
    if Runlevel.runlevel0 < runlevel < Runlevel.runlevel6:
        system_manager = get_system_manager()
        if system_manager == SystemManagerType.systemd:
            TestRun.executor.run_expect_success(f"systemctl set-default {runlevel.name}.target")
        else:
            TestRun.executor.run_expect_success(
                f"sed -i 's/^.*id:.*$/id:{runlevel.value}:initdefault: /' /etc/inittab")
            TestRun.executor.run_expect_success(f"init {runlevel.value}")


def get_runlevel():
    system_manager = get_system_manager()
    if system_manager == SystemManagerType.systemd:
        result = TestRun.executor.run_expect_success("systemctl get-default")
        try:
            name = result.stdout.split(".")[0].replace("-", "_")
            return Runlevel[name]
        except Exception:
            raise Exception(f"Cannot parse '{result.output}' to runlevel.")
    else:
        result = TestRun.executor.run_expect_success("runlevel")
        try:
            split_output = result.stdout.split()
            runlevel = Runlevel(int(split_output[1]))
            return runlevel
        except Exception:
            raise Exception(f"Cannot parse '{result.output}' to runlevel.")


class Udev(object):
    @staticmethod
    def enable():
        TestRun.LOGGER.info("Enabling udev")
        TestRun.executor.run_expect_success("udevadm control --start-exec-queue")

    @staticmethod
    def disable():
        TestRun.LOGGER.info("Disabling udev")
        TestRun.executor.run_expect_success("udevadm control --stop-exec-queue")

    @staticmethod
    def trigger():
        TestRun.executor.run_expect_success("udevadm trigger")

    @staticmethod
    def settle():
        TestRun.executor.run_expect_success("udevadm settle")


def drop_caches(level: DropCachesMode = DropCachesMode.ALL):
    TestRun.executor.run_expect_success(
        f"echo {level.value} > /proc/sys/vm/drop_caches")


def disable_memory_affecting_functions():
    """Disables system functions affecting memory"""
    # Don't allow sshd to be killed in case of out-of-memory:
    TestRun.executor.run(
        "echo '-1000' > /proc/`cat /var/run/sshd.pid`/oom_score_adj"
    )
    TestRun.executor.run(
        "echo -17 > /proc/`cat /var/run/sshd.pid`/oom_adj"
    )  # deprecated
    TestRun.executor.run_expect_success(
        f"echo {OvercommitMemoryMode.NEVER.value} > /proc/sys/vm/overcommit_memory"
    )
    TestRun.executor.run_expect_success("echo '100' > /proc/sys/vm/overcommit_ratio")
    TestRun.executor.run_expect_success(
        "echo '64      64      32' > /proc/sys/vm/lowmem_reserve_ratio"
    )
    TestRun.executor.run_expect_success("swapoff --all")
    drop_caches(DropCachesMode.SLAB)


def defaultize_memory_affecting_functions():
    """Sets default values to system functions affecting memory"""
    TestRun.executor.run_expect_success(
        f"echo {OvercommitMemoryMode.DEFAULT.value} > /proc/sys/vm/overcommit_memory"
    )
    TestRun.executor.run_expect_success("echo 50 > /proc/sys/vm/overcommit_ratio")
    TestRun.executor.run_expect_success(
        "echo '256     256     32' > /proc/sys/vm/lowmem_reserve_ratio"
    )
    TestRun.executor.run_expect_success("swapon --all")


def get_free_memory():
    """Returns free amount of memory in bytes"""
    output = TestRun.executor.run_expect_success("free -b")
    output = output.stdout.splitlines()
    for line in output:
        if 'free' in line:
            index = line.split().index('free') + 1  # 1st row has 1 element less than following rows
        if 'Mem' in line:
            mem_line = line.split()

    return Size(int(mem_line[index]))


def get_mem_available():
    """Returns amount of available memory from /proc/meminfo"""
    cmd = "cat /proc/meminfo | grep MemAvailable | awk '{ print $2 }'"
    mem_available = TestRun.executor.run(cmd).stdout

    return Size(int(mem_available), Unit.KibiByte)


def get_module_mem_footprint(module_name):
    """Returns allocated size of specific module's metadata from /proc/vmallocinfo"""
    cmd = f"cat /proc/vmallocinfo | grep {module_name} | awk '{{ print $2 }}' "
    output_lines = TestRun.executor.run(cmd).stdout.splitlines()
    memory_used = 0
    for line in output_lines:
        memory_used += int(line)

    return Size(memory_used)


def allocate_memory(size: Size):
    """Allocates given amount of memory"""
    mount_ramfs()
    TestRun.LOGGER.info(f"Allocating {size.get_value(Unit.MiB):0.2f} MiB of memory.")
    bs = Size(1, Unit.Blocks512)
    dd = (
        Dd()
        .block_size(bs)
        .count(math.ceil(size / bs))
        .input("/dev/zero")
        .output(f"{MEMORY_MOUNT_POINT}/data")
    )
    output = dd.run()
    if output.exit_code != 0:
        raise CmdException("Allocating memory failed.", output)


def get_number_of_processors_from_cpuinfo():
    """Returns number of processors (count) which are listed out in /proc/cpuinfo"""
    cmd = f"cat /proc/cpuinfo | grep processor | wc -l"
    output = TestRun.executor.run(cmd).stdout

    return int(output)


def get_number_of_processes(process_name):
    cmd = f"ps aux | grep {process_name} | grep -v grep | wc -l"
    output = TestRun.executor.run(cmd).stdout

    return int(output)


def mount_ramfs():
    """Mounts ramfs to enable allocating memory space"""
    if not check_if_directory_exists(MEMORY_MOUNT_POINT):
        create_directory(MEMORY_MOUNT_POINT)
    if not is_mounted(MEMORY_MOUNT_POINT):
        TestRun.executor.run_expect_success(f"mount -t ramfs ramfs {MEMORY_MOUNT_POINT}")


def unmount_ramfs():
    """Unmounts ramfs and releases whole space allocated by it in memory"""
    TestRun.executor.run_expect_success(f"umount {MEMORY_MOUNT_POINT}")


def download_file(url, destination_dir="/tmp"):
    # TODO use wget module instead
    command = ("wget --tries=3 --timeout=5 --continue --quiet "
               f"--directory-prefix={destination_dir} {url}")
    TestRun.executor.run_expect_success(command)
    path = f"{destination_dir.rstrip('/')}/{File.get_name(url)}"
    return File(path)


def get_kernel_version():
    version_string = TestRun.executor.run_expect_success("uname -r").stdout
    version_string = version_string.split('-')[0]
    return version.Version(version_string)


class ModuleRemoveMethod(Enum):
    rmmod = "rmmod"
    modprobe = "modprobe -r"


def is_kernel_module_loaded(module_name):
    output = TestRun.executor.run(f"lsmod | grep ^{module_name}")
    return output.exit_code == 0


def get_sys_block_path():
    sys_block = "/sys/class/block"
    if not check_if_directory_exists(sys_block):
        sys_block = "/sys/block"
    return sys_block


def load_kernel_module(module_name, module_args: {str, str}=None):
    cmd = f"modprobe {module_name}"
    if module_args is not None:
        for key, value in module_args.items():
            cmd += f" {key}={value}"
    return TestRun.executor.run(cmd)


def unload_kernel_module(module_name, unload_method: ModuleRemoveMethod = ModuleRemoveMethod.rmmod):
    cmd = f"{unload_method.value} {module_name}"
    return TestRun.executor.run_expect_success(cmd)


def get_kernel_module_parameter(module_name, parameter):
    param_file_path = f"/sys/module/{module_name}/parameters/{parameter}"
    if not check_if_file_exists(param_file_path):
        raise FileNotFoundError(f"File {param_file_path} does not exist!")
    return File(param_file_path).read()


def is_mounted(path: str):
    if path is None or path.isspace():
        raise Exception("Checked path cannot be empty")
    command = f"mount | grep --fixed-strings '{path.rstrip('/')} '"
    return TestRun.executor.run(command).exit_code == 0


def mount_debugfs():
    if not is_mounted(DEBUGFS_MOUNT_POINT):
        TestRun.executor.run_expect_success(f"mount -t debugfs none {DEBUGFS_MOUNT_POINT}")


def reload_kernel_module(module_name, module_args: {str, str}=None,
                         unload_method: ModuleRemoveMethod = ModuleRemoveMethod.rmmod):
    if is_kernel_module_loaded(module_name):
        unload_kernel_module(module_name, unload_method)

    Retry.run_while_false(
        lambda: load_kernel_module(module_name, module_args).exit_code == 0,
        timeout=timedelta(seconds=5)
    )


def get_module_path(module_name):
    cmd = f"modinfo {module_name}"

    # module path is in second column of first line of `modinfo` output
    module_info = TestRun.executor.run_expect_success(cmd).stdout
    module_path = module_info.splitlines()[0].split()[1]

    return module_path


def get_executable_path(exec_name):
    cmd = f"which {exec_name}"

    path = TestRun.executor.run_expect_success(cmd).stdout

    return path


def get_udev_service_path(unit_name):
    cmd = f"systemctl cat {unit_name}"

    # path is in second column of first line of output
    info = TestRun.executor.run_expect_success(cmd).stdout
    path = info.splitlines()[0].split()[1]

    return path


def kill_all_io(graceful=True):
    if graceful:
        # TERM signal should be used in preference to the KILL signal, since a
        # process may install a handler for the TERM signal in order to perform
        # clean-up steps before terminating in an orderly fashion.
        TestRun.executor.run("killall -q --signal TERM dd fio blktrace")
        time.sleep(3)
    TestRun.executor.run("killall -q --signal KILL dd fio blktrace")
    TestRun.executor.run("kill -9 `ps aux | grep -i vdbench.* | awk '{ print $2 }'`")

    if TestRun.executor.run("pgrep -x dd").exit_code == 0:
        raise Exception(f"Failed to stop dd!")
    if TestRun.executor.run("pgrep -x fio").exit_code == 0:
        raise Exception(f"Failed to stop fio!")
    if TestRun.executor.run("pgrep -x blktrace").exit_code == 0:
        raise Exception(f"Failed to stop blktrace!")
    if TestRun.executor.run("pgrep vdbench").exit_code == 0:
        raise Exception(f"Failed to stop vdbench!")


def wait(predicate, timeout: timedelta, interval: timedelta = None):
    start_time = datetime.now()
    result = False
    while start_time + timeout > datetime.now():
        result = predicate()
        if result:
            break
        if interval is not None:
            time.sleep(interval.total_seconds())
    return result


def sync():
    TestRun.executor.run_expect_success("sync")


def get_dut_cpu_number():
    return int(TestRun.executor.run_expect_success("nproc").stdout)


def get_dut_cpu_physical_cores():
    """ Get list of CPU numbers that don't share physical cores """
    output = TestRun.executor.run_expect_success("lscpu --all --parse").stdout

    core_list = []
    visited_phys_cores = []
    for line in output.split("\n"):
        if "#" in line:
            continue

        cpu_no, phys_core_no = line.split(",")[:2]
        if phys_core_no not in visited_phys_cores:
            core_list.append(cpu_no)
            visited_phys_cores.append(phys_core_no)

    return core_list


def set_wbt_lat(device: Device, value: int):
    if value < 0:
        raise ValueError("Write back latency can't be negative number")

    wbt_lat_config_path = posixpath.join(
        get_sysfs_path(device.device_id), "queue/wbt_lat_usec"
    )

    return TestRun.executor.run_expect_success(f"echo {value} > {wbt_lat_config_path}")


def get_wbt_lat(device: Device):
    wbt_lat_config_path = posixpath.join(
        get_sysfs_path(device.device_id), "queue/wbt_lat_usec"
    )

    return int(TestRun.executor.run_expect_success(f"cat {wbt_lat_config_path}").stdout)


def get_cores_ids_range(numa_node: int):
    output = TestRun.executor.run_expect_success(f"lscpu --all --parse").stdout
    parse_output = re.findall(r'(\d+),(\d+),(?:\d+),(\d+),,', output, re.I)

    return [element[0] for element in parse_output if int(element[2]) == numa_node]
