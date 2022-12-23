#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from enum import Enum

from core.test_run import TestRun
from storage_devices.device import Device
from test_utils.disk_finder import resolve_to_by_id_link
from test_utils.linux_command import LinuxCommand
from test_utils.size import Size, Unit


class DmTarget(Enum):
    # Fill argument types for other targets if you need them
    LINEAR = (str, int)
    STRIPED = (int, int, list)
    ERROR = ()
    ZERO = ()
    CRYPT = ()
    DELAY = (str, int, int, str, int, int)
    FLAKEY = (str, int, int, int)
    MIRROR = ()
    MULTIPATH = ()
    RAID = ()
    SNAPSHOT = ()

    def __str__(self):
        return self.name.lower()


class DmTable:
    class TableEntry:
        pass


class DmTable:
    class TableEntry:
        def __init__(self, offset: int, length: int, target: DmTarget, *params):
            self.offset = int(offset)
            self.length = int(length)
            self.target = DmTarget(target)
            self.params = list(params)
            self.validate()

        def validate(self):
            if self.target.value:
                for i in range(len(self.params)):
                    try:
                        self.params[i] = self.target.value[i](self.params[i])
                    except IndexError:
                        raise ValueError("invalid dm target parameter")

        def __str__(self):
            ret = f"{self.offset} {self.length} {self.target}"
            for param in self.params:
                ret += f" {param}"

            return ret

    def __init__(self):
        self.table = []

    @classmethod
    def uniform_error_table(
        cls, start_lba: int, stop_lba: int, num_error_zones: int, error_zone_size: Size
    ):
        table = cls()
        increment = (stop_lba - start_lba) // num_error_zones

        for zone_start in range(start_lba, stop_lba, increment):
            table.add_entry(
                DmTable.TableEntry(
                    zone_start,
                    error_zone_size.get_value(Unit.Blocks512),
                    DmTarget.ERROR,
                )
            )

        return table

    @classmethod
    def passthrough_table(cls, device: Device):
        table = cls()

        table.add_entry(
            DmTable.TableEntry(
                0,
                device.size.get_value(Unit.Blocks512),
                DmTarget.LINEAR,
                device.path,
                0,
            )
        )

        return table

    @classmethod
    def error_table(cls, offset: int, size: Size):
        table = cls()

        table.add_entry(
            DmTable.TableEntry(offset, size.get_value(Unit.Blocks512), DmTarget.ERROR)
        )

        return table

    def fill_gaps(self, device: Device, fill_end=True):
        gaps = self.get_gaps()

        for gap in gaps[:-1]:
            self.add_entry(
                DmTable.TableEntry(
                    gap[0], gap[1], DmTarget.LINEAR, device.path, int(gap[0])
                )
            )

        table_end = gaps[-1][0]

        if fill_end and (Size(table_end, Unit.Blocks512) < device.size):
            self.add_entry(
                DmTable.TableEntry(
                    table_end,
                    device.size.get_value(Unit.Blocks512) - table_end,
                    DmTarget.LINEAR,
                    device.path,
                    table_end,
                )
            )

        return self

    def add_entry(self, entry: DmTable.TableEntry):
        self.table.append(entry)
        return self

    def get_gaps(self):
        if not self.table:
            return [(0, -1)]

        gaps = []

        self.table.sort(key=lambda entry: entry.offset)

        if self.table[0].offset != 0:
            gaps.append((0, self.table[0].offset))

        for e1, e2 in zip(self.table, self.table[1:]):
            if e1.offset + e1.length != e2.offset:
                gaps.append(
                    (e1.offset + e1.length, e2.offset - (e1.offset + e1.length))
                )

        if len(self.table) > 1:
            gaps.append((e2.offset + e2.length, -1))
        else:
            gaps.append((self.table[0].offset + self.table[0].length, -1))

        return gaps

    def validate(self):
        self.table.sort(key=lambda entry: entry.offset)

        if self.table[0].offset != 0:
            raise ValueError(f"dm table should start at LBA 0: {self.table[0]}")

        for e1, e2 in zip(self.table, self.table[1:]):
            if e1.offset + e1.length != e2.offset:
                raise ValueError(
                    f"dm table should not have any holes or overlaps: {e1} -> {e2}"
                )

    def get_size(self):
        self.table.sort(key=lambda entry: entry.offset)

        return Size(self.table[-1].offset + self.table[-1].length, Unit.Blocks512)

    def __str__(self):
        output = ""

        for entry in self.table:
            output += f"{entry}\n"

        return output


class DeviceMapper(LinuxCommand):
    @classmethod
    def remove_all(cls, force=True):
        TestRun.LOGGER.info("Removing all device mapper devices")

        cmd = "dmsetup remove_all"
        if force:
            cmd += " --force"

        return TestRun.executor.run_expect_success(cmd)

    def __init__(self, name: str):
        LinuxCommand.__init__(self, TestRun.executor, "dmsetup")
        self.name = name

    @staticmethod
    def wrap_table(table: DmTable):
        return f"<< ENDHERE\n{str(table)}ENDHERE\n"

    def get_path(self):
        return f"/dev/mapper/{self.name}"

    def clear(self):
        return TestRun.executor.run_expect_success(f"{self.command_name} clear {self.name}")

    def create(self, table: DmTable):
        try:
            table.validate()
        except ValueError:
            for entry in table.table:
                TestRun.LOGGER.error(f"{entry}")
            raise

        TestRun.LOGGER.info(f"Creating device mapper device '{self.name}'")

        for entry in table.table:
            TestRun.LOGGER.debug(f"{entry}")

        return TestRun.executor.run_expect_success(
            f"{self.command_name} create {self.name} {self.wrap_table(table)}"
        )

    def remove(self):
        TestRun.LOGGER.info(f"Removing device mapper device '{self.name}'")

        return TestRun.executor.run_expect_success(f"{self.command_name} remove {self.name}")

    def suspend(self):
        TestRun.LOGGER.info(f"Suspending device mapper device '{self.name}'")
        return TestRun.executor.run_expect_success(f"{self.command_name} suspend {self.name}")

    def resume(self):
        TestRun.LOGGER.info(f"Resuming device mapper device '{self.name}'")
        return TestRun.executor.run_expect_success(f"{self.command_name} resume {self.name}")

    def reload(self, table: DmTable):
        table.validate()
        TestRun.LOGGER.info(f"Reloading table for device mapper device '{self.name}'")

        for entry in table.table:
            TestRun.LOGGER.debug(f"{entry}")

        return TestRun.executor.run_expect_success(
            f"{self.command_name} reload {self.name} {self.wrap_table(table)}"
        )


class ErrorDevice(Device):
    def __init__(self, name: str, base_device: Device, table: DmTable = None):
        self.device = base_device
        self.mapper = DeviceMapper(name)
        self.name = name
        self.table = DmTable.passthrough_table(base_device) if not table else table
        self.active = False
        self.start()
        self.path = resolve_to_by_id_link(self.mapper.get_path().replace('/dev/', ''))

    @property
    def system_path(self):
        if self.active:
            output = TestRun.executor.run_expect_success(f"realpath {self.mapper.get_path()}")

            return output.stdout

        return None

    @property
    def size(self):
        if self.active:
            return self.table.get_size()

        return None

    def start(self):
        self.mapper.create(self.table)
        self.active = True

    def stop(self):
        self.mapper.remove()
        self.active = False

    def change_table(self, table: DmTable, permanent=True):
        if self.active:
            self.mapper.suspend()

        self.mapper.reload(table)

        self.mapper.resume()

        if permanent:
            self.table = table

    def suspend_errors(self):
        empty_table = DmTable.passthrough_table(self.device)
        TestRun.LOGGER.info(f"Suspending issuing errors for error device '{self.name}'")

        self.change_table(empty_table, False)

    def resume_errors(self):
        TestRun.LOGGER.info(f"Resuming issuing errors for error device '{self.name}'")

        self.change_table(self.table, False)

    def suspend(self):
        if not self.active:
            TestRun.LOGGER.warning(
                f"cannot suspend error device '{self.name}'! It's already running"
            )

        self.mapper.suspend()

        self.active = False

    def resume(self):
        if self.active:
            TestRun.LOGGER.warning(
                f"cannot resume error device '{self.name}'! It's already running"
            )

        self.mapper.resume()

        self.active = True
