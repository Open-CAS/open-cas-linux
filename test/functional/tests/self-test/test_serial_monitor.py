#
# Copyright(c) 2026 Unvertical
# SPDX-License-Identifier: BSD-3-Clause
#

import posixpath
import time
import pytest

from core.test_run import TestRun
from test_tools.fs_tools import check_if_directory_exists, create_directory, write_file

# Module init triggers the kernel message selected at build time and fails,
# so the module never stays loaded (unless it dies in init).
trigger_source = """
#include <linux/module.h>

#if defined(TRIGGER_NULL)
static int *volatile null_ptr;
#endif

static int __init trigger_init(void)
{
#if defined(TRIGGER_WARN)
\tWARN(1, "serial monitor test warning");
#elif defined(TRIGGER_BUG)
\tBUG();
#elif defined(TRIGGER_NULL)
\t*null_ptr = 0;
#endif
\treturn -ECANCELED;
}
module_init(trigger_init);

MODULE_DESCRIPTION("Serial monitor test trigger");
MODULE_LICENSE("GPL");
"""

trigger_modules = {
    "smt_warn": "TRIGGER_WARN",
    "smt_bug": "TRIGGER_BUG",
    "smt_null": "TRIGGER_NULL",
}


@pytest.mark.require_plugin("serial_monitor")
def test_serial_monitor_kernel_warning():
    """
    title: Serial monitor detects kernel warning.
    description: |
      Trigger WARN() in kernel module on DUT and check if serial monitor catches it
      on the serial console without interrupting the test.
    pass_criteria:
      - Kernel warning is reported by serial monitor
      - Test is not interrupted
    """
    serial_monitor = TestRun.plugin_manager.get_plugin("serial_monitor")

    with TestRun.step("Build trigger modules"):
        modules_dir = build_trigger_modules()

    with TestRun.step("Trigger kernel warning"):
        with serial_monitor.expect("warning", r"WARNING: .*smt_warn"):
            output = TestRun.executor.run(f"insmod {modules_dir}/smt_warn.ko")
            if output.exit_code == 0:
                TestRun.fail("Trigger module loaded, warning was not triggered")

    with TestRun.step("Check if DUT is still responsive"):
        TestRun.executor.run_expect_success("true")


@pytest.mark.require_plugin("serial_monitor")
@pytest.mark.require_plugin("power_control")
@pytest.mark.parametrize(
    "module, pattern",
    [
        ("smt_bug", r"kernel BUG at .*smt_bug\.c"),
        ("smt_null", r"BUG: kernel NULL pointer dereference"),
    ],
    ids=["bug", "null_deref"],
)
def test_serial_monitor_kernel_bug(module, pattern):
    """
    title: Serial monitor interrupts test on kernel bug.
    description: |
      Trigger kernel bug on DUT while test waits for a long running command and check
      if serial monitor interrupts the test.
    pass_criteria:
      - Kernel bug is reported by serial monitor
      - Test is interrupted before the command finishes
    """
    serial_monitor = TestRun.plugin_manager.get_plugin("serial_monitor")
    power_control = TestRun.plugin_manager.get_plugin("power_control")
    command_duration = 120
    trigger_delay = 5

    with TestRun.step("Power cycle DUT if trigger module from previous run is stuck"):
        # Module that died in init stays in loading state and blocks loading it again
        if check_if_directory_exists(f"/sys/module/{module}"):
            power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Build trigger modules"):
        modules_dir = build_trigger_modules()

    with TestRun.step("Trigger kernel bug while waiting for long running command"):
        TestRun.executor.run_in_background(
            f"sleep {trigger_delay} && insmod {modules_dir}/{module}.ko"
        )
        start = time.monotonic()
        with serial_monitor.expect("bug", pattern):
            try:
                TestRun.executor.run(f"sleep {command_duration}")
            except pytest.fail.Exception as e:
                TestRun.LOGGER.info(f"Test interrupted: {e}")
            else:
                TestRun.fail("Test was not interrupted by kernel bug")
        elapsed = time.monotonic() - start
        TestRun.LOGGER.info(f"Interrupted after {elapsed:.1f}s")
        if elapsed > command_duration / 2:
            TestRun.fail(f"Test interrupted too late ({elapsed:.1f}s)")

    with TestRun.step("Power cycle DUT to recover from kernel bug"):
        power_control.power_cycle(wait_for_connection=True)


def build_trigger_modules():
    modules_dir = posixpath.join(TestRun.TEST_RUN_DATA_PATH, "serial_monitor_trigger")
    create_directory(modules_dir, parents=True)
    write_file(posixpath.join(modules_dir, "trigger.c"), trigger_source)
    kbuild = f"obj-m := {' '.join(f'{name}.o' for name in trigger_modules)}\n"
    for name, define in trigger_modules.items():
        TestRun.executor.run_expect_success(
            f"cp {modules_dir}/trigger.c {modules_dir}/{name}.c"
        )
        kbuild += f"CFLAGS_{name}.o := -D{define}\n"
    write_file(posixpath.join(modules_dir, "Kbuild"), kbuild)
    TestRun.executor.run_expect_success(
        f"make -C /lib/modules/$(uname -r)/build M={modules_dir} modules"
    )
    return modules_dir
