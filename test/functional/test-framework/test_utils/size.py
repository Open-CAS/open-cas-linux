#
# Copyright(c) 2019-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import enum
import math

from multimethod import multimethod


def parse_unit(str_unit: str):
    for u in Unit:
        if str_unit == u.name:
            return u

    if str_unit == "KiB":
        return Unit.KibiByte
    elif str_unit in ["4KiB blocks", "4KiB Blocks"]:
        return Unit.Blocks4096
    elif str_unit == "MiB":
        return Unit.MebiByte
    elif str_unit == "GiB":
        return Unit.GibiByte
    elif str_unit == "TiB":
        return Unit.TebiByte

    if str_unit == "B":
        return Unit.Byte
    elif str_unit == "KB":
        return Unit.KiloByte
    elif str_unit == "MB":
        return Unit.MegaByte
    elif str_unit == "GB":
        return Unit.GigaByte
    elif str_unit == "TB":
        return Unit.TeraByte

    raise ValueError(f"Unable to parse {str_unit}")


class Unit(enum.Enum):
    Byte = 1
    KiloByte = 1000
    KibiByte = 1024
    MegaByte = 1000 * KiloByte
    MebiByte = 1024 * KibiByte
    GigaByte = 1000 * MegaByte
    GibiByte = 1024 * MebiByte
    TeraByte = 1000 * GigaByte
    TebiByte = 1024 * GibiByte
    Blocks512 = 512
    Blocks4096 = 4096

    KiB = KibiByte
    KB = KiloByte
    MiB = MebiByte
    MB = MegaByte
    GiB = GibiByte
    GB = GigaByte
    TiB = TebiByte
    TB = TeraByte

    def get_value(self):
        return self.value

    def __str__(self):
        return self.get_name()

    def get_name(self):
        return self.name

    def get_short_name(self):
        if self == Unit.Byte:
            return "B"
        elif self == Unit.KibiByte:
            return "KiB"
        elif self == Unit.KiloByte:
            return "KB"
        elif self == Unit.MebiByte:
            return "MiB"
        elif self == Unit.MegaByte:
            return "MB"
        elif self == Unit.GibiByte:
            return "GiB"
        elif self == Unit.GigaByte:
            return "GB"
        elif self == Unit.TebiByte:
            return "TiB"
        elif self == Unit.TeraByte:
            return "TB"
        raise ValueError(f"Unable to get short unit name for {self}.")


class UnitPerSecond:
    def __init__(self, unit):
        self.value = unit.get_value()
        self.name = unit.name + "/s"

    def get_value(self):
        return self.value


class Size:
    def __init__(self, value: float, unit: Unit = Unit.Byte):
        if value < 0:
            raise ValueError("Size has to be positive.")
        self.value = value * unit.value
        self.unit = unit

    def __str__(self):
        return f"{self.get_value(self.unit)} {self.unit}"

    def __hash__(self):
        return self.value.__hash__()

    def __int__(self):
        return int(self.get_value())

    def __add__(self, other):
        return Size(self.get_value() + other.get_value())

    def __lt__(self, other):
        return self.get_value() < other.get_value()

    def __le__(self, other):
        return self.get_value() <= other.get_value()

    def __eq__(self, other):
        return self.get_value() == other.get_value()

    def __ne__(self, other):
        return self.get_value() != other.get_value()

    def __gt__(self, other):
        return self.get_value() > other.get_value()

    def __ge__(self, other):
        return self.get_value() >= other.get_value()

    def __radd__(self, other):
        return Size(other + self.get_value())

    def __sub__(self, other):
        if self < other:
            raise ValueError("Subtracted value is too big. Result size cannot be negative.")
        return Size(self.get_value() - other.get_value())

    @multimethod
    def __mul__(self, other: int):
        return Size(math.ceil(self.get_value() * other))

    @multimethod
    def __rmul__(self, other: int):
        return Size(math.ceil(self.get_value() * other))

    @multimethod
    def __mul__(self, other: float):
        return Size(math.ceil(self.get_value() * other))

    @multimethod
    def __rmul__(self, other: float):
        return Size(math.ceil(self.get_value() * other))

    @multimethod
    def __truediv__(self, other):
        if other.get_value() == 0:
            raise ValueError("Divisor must not be equal to 0.")
        return self.get_value() / other.get_value()

    @multimethod
    def __truediv__(self, other: int):
        if other == 0:
            raise ValueError("Divisor must not be equal to 0.")
        return Size(math.ceil(self.get_value() / other))

    def set_unit(self, new_unit: Unit):
        new_size = Size(self.get_value(target_unit=new_unit), unit=new_unit)

        if new_size != self:
            raise ValueError(f"{new_unit} is not precise enough for {self}")

        self.value = new_size.value
        self.unit = new_size.unit

        return self

    def get_value(self, target_unit: Unit = Unit.Byte):
        return self.value / target_unit.value

    def is_zero(self):
        if self.value == 0:
            return True
        else:
            return False

    def align_up(self, alignment):
        if self == self.align_down(alignment):
            return Size(int(self))
        return Size(int(self.align_down(alignment)) + alignment)

    def align_down(self, alignment):
        if alignment <= 0:
            raise ValueError("Alignment must be a positive value!")
        if alignment & (alignment - 1):
            raise ValueError("Alignment must be a power of two!")
        return Size(int(self) & ~(alignment - 1))

    @staticmethod
    def zero():
        return Size(0)
