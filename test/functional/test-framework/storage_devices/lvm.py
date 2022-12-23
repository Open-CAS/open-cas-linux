#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import threading

from typing import Union

from api.cas.core import Core
from core.test_run import TestRun
from storage_devices.device import Device
from storage_devices.disk import Disk, NvmeDisk
from storage_devices.partition import Partition
from test_tools.fs_utils import readlink
from test_utils.disk_finder import resolve_to_by_id_link
from test_utils.filesystem.symlink import Symlink
from test_utils.size import Size

lvm_config_path = "/etc/lvm/lvm.conf"
filter_prototype_regex = r"^\sfilter\s=\s\["
types_prototype_regex = r"^\stypes\s=\s\["
global_filter_prototype_regex = r"^\sglobal_filter\s=\s\["
tab = "\\\\t"


class LvmConfiguration:
    def __init__(
            self,
            lvm_filters: [] = None,
            pv_num: int = None,
            vg_num: int = None,
            lv_num: int = None,
            cache_num: int = None,
            cas_dev_num: int = None
    ):
        self.lvm_filters = lvm_filters
        self.pv_num = pv_num
        self.vg_num = vg_num
        self.lv_num = lv_num
        self.cache_num = cache_num
        self.cas_dev_num = cas_dev_num

    @staticmethod
    def __read_definition_from_lvm_config(
            prototype_regex: str
    ):
        cmd = f"grep '{prototype_regex}' {lvm_config_path}"
        output = TestRun.executor.run(cmd).stdout

        return output

    @classmethod
    def __add_block_dev_to_lvm_config(
            cls,
            block_device_type: str,
            number_of_partitions: int = 16
    ):
        types_definition = cls.read_types_definition_from_lvm_config()

        if types_definition:
            if block_device_type in types_definition:
                TestRun.LOGGER.info(f"Device type '{block_device_type}' already present in config")
                return

            TestRun.LOGGER.info(f"Add block device type to existing list")
            new_type_prefix = f"types = [\"{block_device_type}\", {number_of_partitions}, "

            config_update_cmd = f"sed -i 's/{types_prototype_regex}/\t{new_type_prefix}/g'" \
                                f" {lvm_config_path}"
        else:
            TestRun.LOGGER.info(f"Create new types variable")
            new_types = f"types = [\"{block_device_type}\", {number_of_partitions}]"
            characteristic_line = f"# Configuration option devices\\/sysfs_scan."
            config_update_cmd = f"sed -i /'{characteristic_line}'/i\\ '{tab}{new_types}' " \
                                f"{lvm_config_path}"

        TestRun.LOGGER.info(f"Adding {block_device_type} ({number_of_partitions} partitions) "
                            f"to supported types in {lvm_config_path}")
        TestRun.executor.run(config_update_cmd)

    @classmethod
    def __add_filter_to_lvm_config(
            cls,
            filter: str
    ):
        if filter is None:
            TestRun.LOGGER.error(f"Lvm filter for lvm config not provided.")

        filters_definition = cls.read_filter_definition_from_lvm_config()

        if filters_definition:
            if filter in filters_definition:
                TestRun.LOGGER.info(f"Filter definition '{filter}' already present in config")
                return

            new_filter_formatted = filter.replace("/", "\\/")
            new_filter_prefix = f"filter = [ \"{new_filter_formatted}\", "

            TestRun.LOGGER.info(f"Adding filter to existing list")
            config_update_cmd = f"sed -i 's/{filter_prototype_regex}/\t{new_filter_prefix}/g'" \
                                f" {lvm_config_path}"
        else:
            TestRun.LOGGER.info(f"Create new filter variable")
            new_filter = f"filter = [\"{filter}\"]"
            characteristic_line = f"# Configuration option devices\\/global_filter."
            config_update_cmd = f"sed -i /'{characteristic_line}'/i\\ '{tab}{new_filter}' " \
                                f"{lvm_config_path}"

        TestRun.LOGGER.info(f"Adding filter '{filter}' to {lvm_config_path}")
        TestRun.executor.run(config_update_cmd)

    @classmethod
    def read_types_definition_from_lvm_config(cls):
        return cls.__read_definition_from_lvm_config(types_prototype_regex)

    @classmethod
    def read_filter_definition_from_lvm_config(cls):
        return cls.__read_definition_from_lvm_config(filter_prototype_regex)

    @classmethod
    def read_global_filter_definition_from_lvm_config(cls):
        return cls.__read_definition_from_lvm_config(global_filter_prototype_regex)

    @classmethod
    def add_block_devices_to_lvm_config(
            cls,
            device_type: str
    ):
        if device_type is None:
            TestRun.LOGGER.error(f"No device provided.")

        cls.__add_block_dev_to_lvm_config(device_type)

    @classmethod
    def add_filters_to_lvm_config(
            cls,
            filters: []
    ):
        if filters is None:
            TestRun.LOGGER.error(f"Lvm filters for lvm config not provided.")

        for f in filters:
            cls.__add_filter_to_lvm_config(f)

    @classmethod
    def configure_dev_types_in_config(
            cls,
            devices: ([Device], Device)
    ):
        if isinstance(devices, list):
            devs = []
            for device in devices:
                dev = device.parent_device if isinstance(device, Partition) else device
                devs.append(dev)

            if any(isinstance(dev, Core) for dev in devs):
                cls.add_block_devices_to_lvm_config("cas")
            if any(isinstance(dev, NvmeDisk) for dev in devs):
                cls.add_block_devices_to_lvm_config("nvme")
        else:
            dev = devices.parent_device if isinstance(devices, Partition) else devices
            if isinstance(dev, Core):
                cls.add_block_devices_to_lvm_config("cas")
            if isinstance(dev, NvmeDisk):
                cls.add_block_devices_to_lvm_config("nvme")

    @classmethod
    def configure_filters(
            cls,
            lvm_filters: [],
            devices: ([Device], Device)
    ):
        if lvm_filters:
            TestRun.LOGGER.info(f"Preparing configuration for LVMs - filters.")
            LvmConfiguration.add_filters_to_lvm_config(lvm_filters)

        cls.configure_dev_types_in_config(devices)

    @staticmethod
    def remove_global_filter_from_config():
        cmd = f"sed -i '/{global_filter_prototype_regex}/d' {lvm_config_path}"
        TestRun.executor.run(cmd)

    @staticmethod
    def remove_filters_from_config():
        cmd = f"sed -i '/{filter_prototype_regex}/d' {lvm_config_path}"
        TestRun.executor.run(cmd)


class VolumeGroup:
    __unique_vg_id = 0
    __lock = threading.Lock()

    def __init__(self, name: str = None):
        self.name = name

    def __eq__(self, other):
        try:
            return self.name == other.name
        except AttributeError:
            return False

    @classmethod
    def __get_vg_name(cls, prefix: str = "vg"):
        with cls.__lock:
            cls.__unique_vg_id += 1
            return f"{prefix}{cls.__unique_vg_id}"

    @staticmethod
    def get_all_volume_groups():
        output_lines = TestRun.executor.run(f"pvscan").stdout.splitlines()

        volume_groups = {}
        for line in output_lines:
            if "PV" not in line:
                continue

            line_elements = line.split()
            pv = line_elements[line_elements.index("PV") + 1]
            vg = ""
            if "VG" in line:
                vg = line_elements[line_elements.index("VG") + 1]

            if vg not in volume_groups:
                volume_groups[vg] = []
            volume_groups[vg].append(pv)

        return volume_groups

    @staticmethod
    def create_vg(vg_name: str, device_paths: str):
        if not vg_name:
            raise ValueError("Name needed for VG creation.")
        if not device_paths:
            raise ValueError("Device paths needed for VG creation.")

        cmd = f"vgcreate --yes {vg_name} {device_paths} "
        TestRun.executor.run_expect_success(cmd)

    @classmethod
    def is_vg_already_present(cls, dev_number: int, device_paths: str = None):
        if not device_paths:
            TestRun.LOGGER.exception("No devices provided.")

        volume_groups = cls.get_all_volume_groups()

        for vg in volume_groups:
            for pv in volume_groups[vg]:
                if len(volume_groups[vg]) == dev_number and pv in device_paths:
                    return cls(vg)

        for vg in volume_groups:
            for pv in volume_groups[vg]:
                if pv in device_paths:
                    TestRun.LOGGER.warning(f"Some devices are used in other LVM volume group")
        return False

    @classmethod
    def create(cls, device_paths: str = None):
        vg_name = cls.__get_vg_name()

        VolumeGroup.create_vg(vg_name, device_paths)

        volume_groups = VolumeGroup.get_all_volume_groups()

        if vg_name in volume_groups:
            return cls(vg_name)
        else:
            TestRun.LOGGER.error("Had not found newly created VG.")

    @staticmethod
    def remove(vg_name: str):
        if not vg_name:
            raise ValueError("Name needed for VG remove operation.")

        cmd = f"vgremove {vg_name}"
        return TestRun.executor.run(cmd)

    @staticmethod
    def get_logical_volumes_path(vg_name: str):
        cmd = f"lvdisplay | grep /dev/{vg_name}/ | awk '{{print $3}}'"
        paths = TestRun.executor.run(cmd).stdout.splitlines()

        return paths


class Lvm(Disk):
    __unique_lv_id = 0
    __lock = threading.Lock()

    def __init__(
            self,
            path_dm: str,  # device mapper path
            volume_group: VolumeGroup,
            volume_name: str = None
    ):
        Device.__init__(self, resolve_to_by_id_link(path_dm))
        self.device_name = path_dm.split('/')[-1]
        self.volume_group = volume_group
        self.volume_name = volume_name

    def __eq__(self, other):
        try:
            return self.device_name == other.device_name and \
                self.volume_group == other.volume_group and \
                self.volume_name == other.volume_name
        except AttributeError:
            return False

    @classmethod
    def __get_unique_lv_name(cls, prefix: str = "lv"):
        with cls.__lock:
            cls.__unique_lv_id += 1
            return f"{prefix}{cls.__unique_lv_id}"

    @classmethod
    def __create(
            cls,
            name: str,
            volume_size_cmd: str,
            volume_group: VolumeGroup
    ):
        TestRun.LOGGER.info(f"Creating LV '{name}'.")
        cmd = f"lvcreate {volume_size_cmd} --name {name} {volume_group.name} --yes"
        TestRun.executor.run_expect_success(cmd)

        volumes = cls.discover_logical_volumes()
        for volume in volumes:
            if name == volume.volume_name:
                return volume

    @classmethod
    def configure_global_filter(
            cls,
            dev_first: Device,
            lv_amount: int,
            pv_devs: ([Device], Device)
    ):
        device_first = dev_first.parent_device if isinstance(dev_first, Partition) else dev_first
        if lv_amount > 1 and isinstance(device_first, Core):

            global_filter_def = LvmConfiguration.read_global_filter_definition_from_lvm_config()
            if not isinstance(pv_devs, list):
                pv_devs = [pv_devs]

            if global_filter_def:
                TestRun.LOGGER.info(f"Configure 'global filter' variable")
                links = []
                for pv_dev in pv_devs:
                    link = pv_dev.get_device_link("/dev/disk/by-id")
                    links.append(str(link))

                for link in links:
                    if link in global_filter_def:
                        TestRun.LOGGER.info(f"Global filter definition already contains '{link}'")
                        continue

                    new_link_formatted = link.replace("/", "\\/")
                    new_global_filter_prefix = f"global_filter = [ \"r|{new_link_formatted}|\", "

                    TestRun.LOGGER.info(f"Adding global filter '{link}' to existing list")
                    config_update_cmd = f"sed -i 's/{global_filter_prototype_regex}/\t" \
                                        f"{new_global_filter_prefix}/g' {lvm_config_path}"
                    TestRun.executor.run(config_update_cmd)
            else:
                for pv_dev in pv_devs:
                    link = pv_dev.get_device_link("/dev/disk/by-id")
                    global_filter = f"\"r|{link}|\""
                    global_filter += ", "
                global_filter = global_filter[:-2]

                TestRun.LOGGER.info(f"Create new 'global filter' variable")

                new_global = f"global_filter = [{global_filter}]"
                characteristic_line = f"# Configuration option devices\\/types."
                config_update_cmd = f"sed -i /'{characteristic_line}'/i\\ " \
                                    f"'{tab}{new_global}' {lvm_config_path}"

                TestRun.LOGGER.info(f"Adding global filter '{global_filter}' to {lvm_config_path}")
                TestRun.executor.run(config_update_cmd)

            TestRun.LOGGER.info(f"Remove 'filter' in order to 'global_filter' to be used")
            if LvmConfiguration.read_filter_definition_from_lvm_config():
                LvmConfiguration.remove_filters_from_config()

    @classmethod
    def create_specific_lvm_configuration(
            cls,
            devices: ([Device], Device),
            lvm_configuration: LvmConfiguration,
            lvm_as_core: bool = False
    ):
        pv_per_vg = int(lvm_configuration.pv_num / lvm_configuration.vg_num)
        lv_per_vg = int(lvm_configuration.lv_num / lvm_configuration.vg_num)
        lv_size_percentage = int(100 / lv_per_vg)

        LvmConfiguration.configure_filters(lvm_configuration.lvm_filters, devices)

        logical_volumes = []

        for vg_iter in range(lvm_configuration.vg_num):
            if isinstance(devices, list):
                pv_devs = []
                start_range = vg_iter * pv_per_vg
                end_range = start_range + pv_per_vg
                for i in range(start_range, end_range):
                    pv_devs.append(devices[i])
                device_first = devices[0]
            else:
                pv_devs = devices
                device_first = devices

            for j in range(lv_per_vg):
                lv = cls.create(lv_size_percentage, pv_devs)
                logical_volumes.append(lv)

            if lvm_as_core:
                cls.configure_global_filter(device_first, lv_per_vg, pv_devs)

        return logical_volumes

    @classmethod
    def create(
            cls,
            volume_size_or_percent: Union[Size, int],
            devices: ([Device], Device),
            name: str = None
    ):
        if isinstance(volume_size_or_percent, Size):
            size_cmd = f"--size {volume_size_or_percent.get_value()}B"
        elif isinstance(volume_size_or_percent, int):
            size_cmd = f"--extents {volume_size_or_percent}%VG"
        else:
            TestRun.LOGGER.error(f"Incorrect type of the first argument (volume_size_or_percent).")

        if not name:
            name = cls.__get_unique_lv_name()

        devices_paths = cls.get_devices_path(devices)
        dev_number = len(devices) if isinstance(devices, list) else 1

        vg = VolumeGroup.is_vg_already_present(dev_number, devices_paths)

        if not vg:
            vg = VolumeGroup.create(devices_paths)

        return cls.__create(name, size_cmd, vg)

    @staticmethod
    def get_devices_path(devices: ([Device], Device)):
        if isinstance(devices, list):
            return " ".join([Symlink(dev.path).get_target() for dev in devices])
        else:
            return Symlink(devices.path).get_target()

    @classmethod
    def discover_logical_volumes(cls):
        vol_groups = VolumeGroup.get_all_volume_groups()
        volumes = []
        for vg in vol_groups:
            lv_discovered = VolumeGroup.get_logical_volumes_path(vg)
            if lv_discovered:
                for lv_path in lv_discovered:
                    cls.make_sure_lv_is_active(lv_path)
                    lv_name = lv_path.split('/')[-1]
                    volumes.append(
                        cls(
                            readlink(lv_path),
                            VolumeGroup(vg),
                            lv_name
                        )
                    )
            else:
                TestRun.LOGGER.info(f"No LVMs present in the system.")

        return volumes

    @classmethod
    def discover(cls):
        TestRun.LOGGER.info("Discover LVMs in system...")
        return cls.discover_logical_volumes()

    @staticmethod
    def remove(lv_name: str, vg_name: str):
        if not lv_name:
            raise ValueError("LV name needed for LV remove operation.")
        if not vg_name:
            raise ValueError("VG name needed for LV remove operation.")

        cmd = f"lvremove -f {vg_name}/{lv_name}"
        return TestRun.executor.run(cmd)

    @staticmethod
    def remove_pv(pv_name: str):
        if not pv_name:
            raise ValueError("Name needed for PV remove operation.")

        cmd = f"pvremove {pv_name}"
        return TestRun.executor.run(cmd)

    @classmethod
    def remove_all(cls):
        cmd = f"lvdisplay | grep 'LV Path' | awk '{{print $3}}'"
        lvm_paths = TestRun.executor.run(cmd).stdout.splitlines()
        for lvm_path in lvm_paths:
            lv_name = lvm_path.split('/')[-1]
            vg_name = lvm_path.split('/')[-2]
            cls.remove(lv_name, vg_name)

        cmd = f"vgdisplay | grep 'VG Name' | awk '{{print $3}}'"
        vg_names = TestRun.executor.run(cmd).stdout.splitlines()
        for vg_name in vg_names:
            TestRun.executor.run(f"vgchange -an {vg_name}")
            VolumeGroup.remove(vg_name)

        cmd = f"pvdisplay | grep 'PV Name' | awk '{{print $3}}'"
        pv_names = TestRun.executor.run(cmd).stdout.splitlines()
        for pv_name in pv_names:
            cls.remove_pv(pv_name)

        TestRun.LOGGER.info(f"Successfully removed all LVMs.")

    @staticmethod
    def make_sure_lv_is_active(lv_path: str):
        cmd = f"lvscan"
        output_lines = TestRun.executor.run_expect_success(cmd).stdout.splitlines()

        for line in output_lines:
            if "inactive " in line and lv_path in line:
                cmd = f"lvchange -ay {lv_path}"
                TestRun.executor.run_expect_success(cmd)
